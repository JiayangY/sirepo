# -*- coding: utf-8 -*-
u"""simulation data operations

:copyright: Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from pykern.pkcollections import PKDict
from pykern.pkdebug import pkdc, pkdlog, pkdp
import sirepo.sim_data


class SimData(sirepo.sim_data.SimDataBase):

    @classmethod
    def fixup_old_data(cls, data):
        dm = data.models
        cls._init_models(
            dm,
            (
                'SPNTRK',
                'SRLOSS',
                'bunch',
                'bunchAnimation',
                'bunchAnimation2',
                'elementStepAnimation',
                'energyAnimation',
                'opticsReport',
                'particle',
                'particleAnimation',
                'particleCoordinate',
                'simulationSettings',
                'tunesReport',
                'twissReport2',
                'twissSummaryReport',
            ),
        )
        if 'coordinates' not in dm.bunch:
            b = dm.bunch
            b.coordinates = []
            for _ in range(b.particleCount2):
                c = PKDict()
                cls.update_model_defaults(c, 'particleCoordinate')
                b.coordinates.append(c)
        # move spntrk from simulationSettings (older) or bunch if present
        for m in 'simulationSettings', 'bunch':
            if 'spntrk' in dm:
                dm.SPNTRK.KSO = dm[m].spntrk
                del dm[m]['spntrk']
                for f in 'S_X', 'S_Y', 'S_Z':
                    if f in dm[m]:
                        dm.SPNTRK[f] = dm[m][f]
                        del dm[m][f]
        for e in dm.elements:
            cls.update_model_defaults(e, e.type)
        cls._organize_example(data)

    @classmethod
    def _compute_job_fields(cls, data, r, compute_model):
        if r == compute_model:
            return []
        if r == 'tunesReport':
            return [r, 'bunchAnimation.startTime']
        res = ['particle', 'bunch']
        if 'bunchReport' in r:
            if data.models.bunch.match_twiss_parameters == '1':
                res.append('simulation.visualizationBeamlineId')
        res += [
            'beamlines',
            'elements',
        ]
        if r == 'twissReport':
            res.append('simulation.activeBeamlineId')
        if r == 'twissReport2' or 'opticsReport' in r or r == 'twissSummaryReport':
            res.append('simulation.visualizationBeamlineId')
        return res

    @classmethod
    def _compute_model(cls, analysis_model, , *args, **kwargs):
        if 'bunchReport' in analysis_model:
            return 'bunchReport'
        return super()._compute_model(analysis_model, *args, **kwargs)

    @classmethod
    def _lib_files(cls, data):
        res = []
        for el in data.models.elements:
            if el.type == 'TOSCA' and el.magnetFile:
                res.append(cls.lib_file_name('TOSCA', 'magnetFile', el.magnetFile))
        return res
