#!/bin/bash
export PYKERN_PKDEBUG_CONTROL=
export PYKERN_PKDEBUG_OUTPUT=
export PYKERN_PKDEBUG_WANT_PID_TIME=1
export SIREPO_FEATURE_CONFIG_JOB_SUPERVISOR=1
export SIREPO_JOB_SUPERVISOR_URI=http://$(hostname):8001
export SIREPO_MPI_CORES=4
if [[ ${1:-} != nersc ]]; then
    export SIREPO_SIMULATION_DB_SBATCH_DISPLAY='V8 Cluster'
else
    export SIREPO_SIMULATION_DB_SBATCH_DISPLAY='Cori@NERSC'
fi
echo "$SIREPO_SIMULATION_DB_SBATCH_DISPLAY"
PYENV_VERSION=py2 pyenv exec sirepo service http
