# -*- coding: utf-8 -*-
u"""request input parsing

:copyright: Copyright (c) 2018 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from pykern.pkcollections import PKDict
from pykern.pkdebug import pkdc, pkdexc, pkdlog, pkdp
from sirepo import util
import flask
import sirepo.template
import user_agents


def is_spider():
    return user_agents.parse(flask.request.headers.get('User-Agent')).is_bot


def parse_data_input(validate=False):
    from sirepo import simulation_db

    data = parse_json(assert_sim_type=False)
    return simulation_db.fixup_old_data(data)[0] if validate else data


def parse_json(assert_sim_type=True):
    from sirepo import simulation_db

    #POSIT: uri_router.call_api
    if hasattr(flask.g, 'sirepo_call_api_data') and flask.g.sirepo_call_api_data:
        return flask.g.sirepo_call_api_data
    req = flask.request
    if req.mimetype != 'application/json':
        util.raise_bad_request(
            'content-type is not application/json: mimetype={}',
            req.mimetype,
        )
    # Adapted from flask.wrappers.Request.get_json
    # We accept a request charset against the specification as
    # certain clients have been using this in the past.  This
    # fits our general approach of being nice in what we accept
    # and strict in what we send out.
    charset = req.mimetype_params.get('charset')
    data = req.get_data(cache=False)
    res = simulation_db.json_load(data, encoding=charset)
    if assert_sim_type and 'simulationType' in res:
        res.simulationType = sirepo.template.assert_sim_type(res.simulationType)
    return res


def parse_sim(req, **kwargs):
    import sirepo.template
    import sirepo.simulation_db
    import sirepo.sim_data

    k = PKDict(kwargs)
    res = PKDict(type=sirepo.template.assert_sim_type(req.simulationType))
    res.sim_data = sirepo.sim_data.get_class(res.type)
    if k.pkdel('id'):
        res.id = res.sim_data.parse_sid(req)
    if k.pkdel('model'):
        res.model = res.sim_data.parse_model(req)
    return res
