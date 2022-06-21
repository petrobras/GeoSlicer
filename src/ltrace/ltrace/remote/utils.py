import json
from pathlib import Path

from ltrace.slicer_utils import print_debug


def argstring(params):
    cli_kwargs = []
    for key, value in params.items():
        if value is None:
            continue

        if isinstance(value, (list, tuple)):
            str_value = ",".join([str(v) for v in value])
        else:
            str_value = str(value)

        # handle a case where a string contains a json structure
        if str_value.startswith("{") and str_value.endswith("}"):
            try:
                # escape all double quotes and single quotes
                str_value = str_value.replace('"', '\\"').replace("'", '\\"')

                json.loads(str_value)
            except json.JSONDecodeError:
                pass

        if " " in str_value and not str_value.startswith('"'):
            str_value = rf'"{str_value}"'

        suffix = "--" if len(key) > 1 else "-"
        cli_kwargs.append(f"{suffix}{key} {str_value}")

    kwargs = " ".join(cli_kwargs)

    return kwargs


def remote_hash(client, location: Path):
    out = client.run_command(f'md5sum "{location}"')

    if len(out["stderr"]) > 0:
        print("Error during hash check: ", out["stderr"])
        raise TimeoutError()

    tokens = out["stdout"].split("  ")
    return tokens[0]


def sacct(client, jobs: list):
    """Get job information from slurm
    client: connection
    jobs: list of job ids
    """
    import logging

    if not jobs:
        return []

    job_id = ",".join(jobs)
    output = client.run_command(f"sacct -P -ojobid,state,elapsed,start,end -j{job_id}")

    if len(output["stderr"]) > 0:
        logging.error("Error during sacct: ", output["stderr"])
        raise RuntimeError(output["stderr"])

    try:
        lines = output["stdout"].strip().split("\n")
        header = lines[0].split("|")
        data = [line.split("|") for line in lines[1:]]
        jobs = [{header[i].lower(): value for i, value in enumerate(row)} for row in data]
        return jobs
    except IndexError as e:
        content = output["stdout"]
        logging.info(f"Unable to parse sacct output. Returning empty list. Received:\n{content}")
        raise RuntimeError(e)
    except Exception as e:
        print_debug(f"Error during sacct parsing: {repr(e)}")
        raise RuntimeError(e)


def any_running(jobs: list):
    """Check if any jobs are running
    jobs: list of job dictionaries
    """
    for job in jobs:
        if job["state"] == "RUNNING":
            return True
    return False


def all_complete(jobs: list):
    """Check if all jobs are complete
    jobs: list of job dictionaries
    """
    for job in jobs:
        if job["state"] != "COMPLETED":
            return False
    return True


def any_failed(jobs: list):
    """Check if any jobs failed
    jobs: list of job dictionaries
    """
    for job in jobs:
        if job["state"] == "FAILED":
            return True
    return False


def all_failed(jobs: list):
    """Check if all jobs failed
    jobs: list of job dictionaries
    """
    for job in jobs:
        if job["state"] != "FAILED":
            return False
    return True


def all_done(jobs: list):
    """Check if all jobs are done
    jobs: list of job dictionaries
    """
    for job in jobs:
        state = job["state"]
        if state != "COMPLETED" and state != "FAILED" and "CANCELLED" not in state:
            return False
    return True


def find_submitted_jobs(jobid: str, logs: dict):
    for filename, log in logs.items():
        if jobid in filename:
            subjobs = []
            for item in log.split("\n"):
                if "Submitted batch job " in item:
                    jid = item[20:].strip()
                    subjobs.append(jid)
            return subjobs
    return None


def look_for_general_tracebacks_on_slurm_logs(client, deploy_path: Path):
    error_check = client.run_command(
        f'if grep -q "Traceback (most recent call last)" {deploy_path}/slurm-*.out; then echo yes; else echo no; fi'
    )

    return error_check["stdout"].strip() == "yes"
