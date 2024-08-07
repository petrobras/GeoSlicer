from datetime import datetime
import logging
import shutil
from typing import Any, Callable
import re
import time
from pathlib import Path, PurePosixPath

from ltrace.remote.utils import argstring, sacct
from ltrace.remote import utils as slurm_utils
from ltrace.remote.jobs import JobManager

import microtom

from ltrace.readers.microtom.utils import parse_command_stdout, node_to_mct_format

import slicer


def truncate_relative_path_on(dirname: str, path: Path):
    relindex = 0
    for i, part in enumerate(path.parts):
        if part == dirname:
            relindex = i + 1

    return Path(*path.parts[relindex:])


class OneResultSlurmHandler:
    JOB_ID_PATTERN = re.compile("job_id = ([a-zA-Z0-9]+)")
    TRACEBACK_PATTERN = r"Traceback[\s\S]*?(?:File[\s\S]*?)+\w+Error:.*"
    MAX_RETRIES = 15

    def __init__(
        self,
        simulator: str,
        collector: Callable,
        input_volume_node,
        shared_path: Path,
        opening_command: str,
        partition: str,
        params: dict,
        prefix: str,
        ref_volume_node_id: str,
        tag: str,
        post_args: dict = None,
    ) -> None:
        self.jobid = None
        self.results = []
        self.simulator = simulator
        self.collector = collector
        self.running_jobs = []
        self.input_volume_node = input_volume_node

        self.img_type = "kabs" if simulator in ["darcy_kabs_foam"] else "bin"

        self.cmd_params = params

        self.prefix = prefix
        self.ref_volume_node_id = ref_volume_node_id
        self.tag = tag

        self.post_args = post_args

        self.command = ""

        self.partition = partition

        self.opening_command = opening_command

        self.jobs = []
        self.closed_jobs = set([])

        self.remote_dir = PurePosixPath(r"/nethome/drp/microtom") / shared_path.as_posix()
        self.local_dir = Path("\\\\dfs.petrobras.biz\\cientifico\\cenpes\\res\\drp\\microtom") / shared_path

        self.is_strict = True

        self.last_slurm_out_size = 0

        self.__action_map = {
            "DEPLOY": self.deploy,
            "START": self.start,
            "PROGRESS": self.progress,
            "CANCEL": self.cancel,
            "COLLECT": self.collect,
        }

        self.retries = 0

    def retrieve_jobinfo_from_file(self, client: Any, deploy_path: Path):
        time.sleep(5)

        jobidcat = client.run_command(f"cat {deploy_path}/job_id;", verbose=True)
        jobid = jobidcat["stdout"].replace("\n", "").strip()

        output = [
            f"work_dir = atena_{jobid}",
            f"job_id = {jobid}",
            f"final_results = {deploy_path}/atena_{jobid}/atena_{jobid}.nc",
        ]

        return output

    def __call__(self, caller: JobManager, uid: str, action: str, **kwargs):
        try:
            client = kwargs.get("client")
            self.__action_map[action](caller, uid, client)
        except KeyError:
            pass

    def deploy(self, caller: JobManager, uid: str, client: Any = None):
        def exportNode(node, direction, img_type, dirpath):
            ds, key = node_to_mct_format(node, direction=direction, img_type=img_type)
            filename = microtom.write_raw_file(ds, save_raw_to=dirpath, data_array=key)
            return filename

        try:
            remote_path = self.remote_dir / uid
            stdout = client.run_command(f"mkdir --parents {remote_path} && chmod -R 777 {remote_path}")
            time.sleep(0.1)
            dest_path = self.local_dir / uid

            if self.simulator == "krel" or self.simulator == "stokes_kabs":
                direction = self.cmd_params.pop("direction", "z")
                self.post_args["direction"] = direction
                filename = exportNode(self.input_volume_node, direction, self.img_type, dest_path)
            else:
                self.post_args["direction"] = self.cmd_params.get("direction", None)
                filename = exportNode(self.input_volume_node, None, self.img_type, dest_path)

            input_image_remote_path = str(remote_path / filename)

            if "diameters" in self.cmd_params:
                diameters = self.cmd_params.pop("diameters")
                args = [argstring(self.cmd_params), input_image_remote_path, diameters]
            else:
                args = [argstring(self.cmd_params), input_image_remote_path]

            s_args = " ".join(args)

            self.command = f"microtom_{self.simulator} {s_args}"

            caller.set_state(uid, "DEPLOYING", 0, message="Configuration done. Starting job deployment.")
            caller.schedule(uid, "START")

        except Exception as e:
            import traceback

            traceback.print_exc()

    def start(self, caller: JobManager, uid: str, client: Any = None):
        tsnow = datetime.now().timestamp()

        try:
            if not self.command:
                caller.set_state(uid, "FAILED", 0, message="Command not defined.")
                return

            deploy_path = self.remote_dir / uid

            if len(self.opening_command.strip()) == 0:
                if caller.jobs[uid].host.opening_command:
                    self.opening_command = caller.jobs[uid].host.opening_command
                else:
                    self.opening_command = "echo 'Opening command not defined. Proceeding with default.'"

            bash_args = " && ".join([self.opening_command, rf"cd {deploy_path}", self.command])
            setup_cmd = rf'bash -c "{bash_args}"'

            output = client.run_command(setup_cmd, verbose=True)

            if len(output["stderr"]) > 0:
                caller.set_state(uid, "FAILED", 0, message="Failed to run command. Check the logs.", traceback=output)
                return

            if self.simulator == "darcy_kabs_foam":
                stdout_items = self.retrieve_jobinfo_from_file(client, deploy_path)
                sim_info = parse_command_stdout(stdout_items)
            else:
                sim_info = parse_command_stdout(output["stdout"].split("\n"))

            self.jobs = [str(j) for j in sim_info["job_id"]]

            if not self.jobs:
                caller.set_state(
                    uid, "FAILED", 100, end_time=tsnow, message="Execution failed to create a job on cluster."
                )
                return

            print(sim_info)
            self.jobid = sim_info["job_id"][0]

            details = {
                **sim_info,
                "simulator": self.simulator,
                "command": self.command,
                "output_prefix": self.prefix,
                "reference_volume_node_id": self.ref_volume_node_id,
                "geoslicer_tag": self.tag,
                **self.post_args,
            }

            caller.set_state(
                uid, "PENDING", 0, message="Job submmited. Waiting for job to start.", start_time=tsnow, details=details
            )
            caller.persist(uid)

            caller.schedule(uid, "PROGRESS")

        except Exception as e:
            import traceback

            traceback.print_exc()
            caller.set_state(
                uid,
                "FAILED",
                0,
                start_time=tsnow,
                end_time=tsnow,
                message="Execution failed to start a job on cluster.",
            )

    def progress(self, caller: JobManager, uid: str, client: Any = None):
        try:
            tsnow = datetime.now().timestamp()

            try:
                jobstatus = sacct(client, self.jobs)
            except RuntimeError as e:
                self.retries += 1

                if self.retries < self.MAX_RETRIES:
                    caller.set_state(
                        uid,
                        "PENDING",
                        0,
                        message="Requesting job status. Waiting for response.",
                        end_time=tsnow,
                        traceback=repr(e),
                    )
                    caller.schedule(uid, "PROGRESS")
                else:
                    caller.set_state(
                        uid,
                        "FAILED",
                        0,
                        message="Failed to get job status. Check yout connection or account authorization.",
                        end_time=tsnow,
                        traceback=repr(e),
                    )

                return

            self.retries = 0

            slurm_out = self.get_slurm_log(uid)

            submitted_jobs = []
            for job in jobstatus:
                if job["jobid"] not in self.closed_jobs:
                    new_jobs = slurm_utils.find_submitted_jobs(job["jobid"], slurm_out)
                    if new_jobs:
                        submitted_jobs.extend(new_jobs)

                    if job["state"] == "COMPLETED":
                        self.closed_jobs.add(job["jobid"])

            # Remove duplicates but keep order
            self.jobs = list(dict.fromkeys([*self.jobs, *submitted_jobs]))

            if slurm_utils.all_done(jobstatus):
                if slurm_utils.all_failed(jobstatus):
                    caller.set_state(
                        uid,
                        "FAILED",
                        0,
                        message="Job(s) failed. Check the logs.",
                        end_time=tsnow,
                        traceback=slurm_out,
                    )
                    return  # EXIT

                # TODO change condition to subprocess is a spawner check
                if self.simulator == "krel":
                    results = self.subprocess_results(self.local_dir / uid / self.simulator)
                else:
                    job = caller.jobs[uid]
                    sim_info = job.details
                    results = []
                    for result_location in sim_info["final_results"]:
                        remote_path = PurePosixPath(result_location)
                        target = truncate_relative_path_on(uid, remote_path)
                        local_file: Path = self.local_dir / uid / target
                        results.append(local_file)

                self.results = []
                seen = set([])
                for r in results:
                    if r not in seen:
                        self.results.append(r)
                        seen.add(r)

                if self.confirm_results(strict=self.is_strict):
                    """job finished and got out of queue"""
                    caller.set_state(
                        uid, "COMPLETED", 100, message="Execution Completed.", end_time=tsnow, traceback=slurm_out
                    )
                else:
                    caller.set_state(
                        uid, "FINISHING", 90, message="Finishing Execution. Waiting for results.", traceback=slurm_out
                    )
                    caller.schedule(uid, "PROGRESS")
            else:
                """If there is still jobs on the list, we just update their status"""
                caller.set_state(uid, "RUNNING", 23, message="Execution in progress.")
                caller.schedule(uid, "PROGRESS")

        except Exception as e:
            import traceback

            traceback.print_exc()

    def cancel(self, caller: JobManager, uid: str, client: Any = None):
        try:
            self.cleanup(caller, uid, client)
            # caller.set_state(uid, "CANCELLED", 0, message="Execution Cancelled.")
        except:
            pass

    def cleanup(self, caller: JobManager, uid: str, client: Any = None):
        ghosted = False
        traceback = None
        if self.jobs:
            stringified_job_list = ",".join(self.jobs)
            try:
                r = client.run_command(f"scancel {stringified_job_list}")

                if len(r["stderr"]) > 0:
                    raise Exception(r["stderr"])
            except Exception as e:
                ghosted = True
                traceback = repr(e)

        if ghosted:
            slurm_out = self.get_slurm_log(uid)
            caller.set_state(
                uid,
                "GHOST",
                0,
                message="Execution cannot be cancelled.",
                traceback={"traceback": traceback, **slurm_out},
            )
            return

        try:
            caller.remove(uid)

            remote_path = self.remote_dir / uid
            """ Note: must be done remotely because of permissions """
            client.run_command(f"rm -rf {remote_path}")
        except Exception:
            local_path = self.local_dir / uid
            if local_path.exists():
                shutil.rmtree(local_path, ignore_errors=True)

    def collect(self, caller: JobManager, uid: str, client: Any = None):
        # TODO use job.details instead of this partial sim_info below
        sim_info = {
            "simulator": self.simulator,
            "command": self.command,
            "output_prefix": self.prefix,
            "reference_volume_node_id": self.ref_volume_node_id,
            "geoslicer_tag": self.tag,
            "results": self.results,
            **self.post_args,
        }
        print(sim_info)
        self.collector(sim_info)

        slicer.util.selectModule("MicroCTEnv")
        slicer.modules.MicroCTEnvWidget.mainTab.setCurrentIndex(0)
        slicer.modules.MicroCTEnvWidget.mainTab.widget(0).setCurrentIndex(0)

        # self.cleanup(caller, uid, client)

    def confirm_results(self, strict=True):
        done = []
        for local_file in self.results:
            done.append(local_file.exists())

        return all(done) if strict else any(done)

    def subprocess_results(self, workdir: Path):
        import os

        results = []
        for sim_dir in workdir.iterdir():
            try:
                k_table = sim_dir / "permeability.csv"
                last_blue = sorted(sim_dir.glob("blue*.vtk"), key=os.path.getmtime, reverse=True)[0]
                last_red = sorted(sim_dir.glob("red*.vtk"), key=os.path.getmtime, reverse=True)[0]

                results.append(k_table)
                results.append(last_blue)
                results.append(last_red)
            except IndexError:
                pass  # no files found
            except Exception as e:
                logging.error(e)

        return results

    def get_slurm_log(self, uid):
        content = {}
        for jobid in self.jobs:
            logfilename = f"slurm-{jobid}.out"
            slurm_path = self.local_dir / uid / logfilename

            if not slurm_path.exists():
                continue

            current_slurm_out_size = slurm_path.stat().st_size

            if self.last_slurm_out_size != current_slurm_out_size:
                with open(slurm_path, "r") as f:
                    slurm_out_content = f.read()

                content[logfilename] = slurm_out_content

        return content
