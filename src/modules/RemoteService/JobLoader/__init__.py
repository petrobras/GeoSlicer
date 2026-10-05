import logging
from importlib import import_module

from ltrace.remote.jobs import JobManager

# (job_type, module, attribute) for every loader the service can mount. Kept as
# data so that importing one is independent of importing the others.
#
# "instseg" is deliberately absent: instseg.py passes an undefined `model`, and
# the handler it builds wants a `ctypes` argument the loader never supplies and
# a REMOTE_DIR its class never defines. It can only raise, and registering it
# just flags its jobs IDLE on every startup. Restore the entry once the loader
# is repaired. "pucnet" is likewise unregistered: pucnet.py is entirely
# commented out.
JOB_LOADERS = (

    ("lbpm", ".lbpm", "lbpm_job_loader"),
    ("microtom", ".microtom", "microtom_job_loader"),
    ("monai", ".monai", "monai_job_loader"),
    ("pnmsimulation", ".pnmsimulation", "pnmsimulation_loader"),
    ("pnmextractor", ".pnmextractor", "pnmextractor_loader"),
    ("pnmkabsrev", ".pnmkabsrev", "pnmkabsrev_loader"),
    ("pnmworkflow", ".pnmworkflow", "pnmworkflow_loader"),
)


def register_job_loaders():
    """Register every job loader that can be imported.

    Each is imported on its own so a broken module costs only the job type it
    serves. The module-level imports this replaces made that failure total: a
    single bad import here failed the whole package, and with it the
    RemoteService module that imports it, leaving no loader registered at all
    and every job silently unmountable.
    """
    registered = []

    for job_type, module_name, attribute in JOB_LOADERS:
        try:
            loader = getattr(import_module(module_name, __name__), attribute)
        except Exception as e:
            logging.error(
                f"Job loader '{job_type}' is unavailable. Jobs of this type will not resume. Cause: {repr(e)}"
            )
            continue

        JobManager.register(job_type, loader)
        registered.append(job_type)

    logging.info(f"Registered job loaders: {', '.join(registered) or 'none'}")

    return registered
