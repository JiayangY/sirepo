# -*- coding: utf-8 -*-
u"""RCSCON simulation data operations

:copyright: Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from pykern.pkcollections import PKDict
from pykern.pkdebug import pkdc, pkdlog, pkdp
import sirepo.sim_data

class SimData(sirepo.sim_data.SimDataBase):

    @classmethod
    def _compute_model(cls, analysis_model, *args, **kwargs):
        if 'fileColumnReport' in analysis_model:
            return 'fileColumnReport'
        if analysis_model == 'epochAnimation' or 'fitAnimation' in analysis_model:
            return 'animation'
        return analysis_model

    @classmethod
    def fixup_old_data(cls, data):
        dm = data.models
        cls._init_models(
            dm,
            (
                'epochAnimation',
                'files',
                'mlModel',
                'neuralNet',
                'neuralNetLayer',
                'partition',
            ))

    @classmethod
    def rcscon_filename(cls, data, model, field):
        return cls.lib_file_name(model, field, data.models[model][field])

    @classmethod
    def _compute_job_fields(cls, data, r, compute_model):
        if 'fileColumnReport' in r:
            return ['files']
        return []

    @classmethod
    def _lib_files(cls, data):
        res = []
        files = data.models.files
        if files.inputs:
            res.append(cls.rcscon_filename(data, 'files', 'inputs'))
        if files.outputs:
            res.append(cls.rcscon_filename(data, 'files', 'outputs'))
        return res