# -*- coding: utf-8 -*-
"""TODO(e-carlin): Doc

:copyright: Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from pykern import pkcollections
from pykern import pkconfig
from pykern.pkcollections import PKDict
from pykern.pkdebug import pkdp, pkdc, pkdlog, pkdexc
from sirepo import job
from sirepo import job_driver
import os
import pykern.pkio
import sirepo.srdb
import sirepo.util
import time
import tornado.ioloop
import tornado.locks


#: where supervisor state is persisted to disk
_DB_DIR = None

#: where job db is stored under srdb.root
_DB_SUBDIR = 'supervisor-job'

_NEXT_REQUEST_SECONDS = PKDict({
    job.PARALLEL: 2,
    job.SBATCH: 10 if pkconfig.channel_in('dev') else 60,
    job.SEQUENTIAL: 1,
})

_RUNNING_PENDING = (job.RUNNING, job.PENDING)


def init():
    global _DB_DIR
    if _DB_DIR:
        return
    job.init()
    job_driver.init()
    _DB_DIR = sirepo.srdb.root().join(_DB_SUBDIR)
    pykern.pkio.mkdir_parent(_DB_DIR)


class ServerReq(PKDict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.uid = self.content.uid
        self._response = None
        self._response_received = tornado.locks.Event()

    async def receive(self):
        self.handler.write(await _ComputeJob.receive(self))


async def terminate():
    await job_driver.terminate()


class _ComputeJob(PKDict):

    instances = PKDict()

    def __init__(self, req, **kwargs):
        c = req.content
        super().__init__(_ops=[], **kwargs)
        self.pksetdefault(db=lambda: self.__db_init(req))

    def destroy_op(self, op):
        self._ops.remove(op)
        op.destroy()

    @classmethod
    def get_instance(cls, req):
        j = req.content.computeJid
        self = cls.instances.pksetdefault(j, lambda: cls.__create(req))[j]
        # SECURITY: must only return instances for authorized user
        assert req.content.uid == self.db.uid, \
            'req.content.uid={} is not same as db.uid={} for jid={}'.format(
                req.content.uid,
                self.db.uid,
                j,
            )
        return self

    @classmethod
    async def receive(cls, req):
        pkdlog('{} jid={}', req.content.api, req.content.computeJid)
        return await getattr(
            cls.get_instance(req),
            '_receive_' + req.content.api,
        )(req)

    @classmethod
    def __create(cls, req):
        try:
            d = pkcollections.json_load_any(
                cls.__db_file(req.content.computeJid),
            )
#TODO(robnagler) when we reconnet with running processes at startup,
#  we'll need to change this
            if d.status in _RUNNING_PENDING:
                d.status = job.CANCELED
            return cls(req, db=d)
        except Exception as e:
            if pykern.pkio.exception_is_not_found(e):
                return cls(req).__db_write()
            raise

    @classmethod
    def __db_file(cls, computeJid):
        return _DB_DIR.join(computeJid + '.json')

    def __db_init(self, req, prev=None):
        c = req.content
        self.db = PKDict(
            computeJid=c.computeJid,
            computeJobHash=c.computeJobHash,
            computeJobStart=0,
            error=None,
            history=self.__db_init_history(prev),
            isParallel=c.isParallel,
            jobRunMode=c.jobRunMode,
            simulationId=c.simulationId,
            simulationType=c.simulationType,
#TODO(robnagler) when would req come in with status?
            status=req.get('status', job.MISSING),
            uid=c.uid,
        )
        self.db.nextRequestSeconds = _NEXT_REQUEST_SECONDS[c.jobRunMode]
        if self.db.isParallel:
            self.db.parallelStatus = PKDict(
                elapsedTime=0,
                frameCount=0,
                lastUpdateTime=0,
                percentComplete=0.0,
                computeJobStart=0,
            )
        return self.db

    def __db_init_history(self, prev):
        if prev is None:
            return PKDict()
        h = prev.history
        if prev.computeJobStart > 0:
            x = h[prev.computeJobStart] = PKDict(
                status=prev.status,
                error=prev.error,
            )
            if prev.isParallel:
                x.lastUpdateTime = prev.parallelStatus.lastUpdateTime
        return h

    def __db_write(self):
        sirepo.util.json_dump(self.db, path=self.__db_file(self.db.computeJid))
        return self

    async def _receive_api_downloadDataFile(self, req):
        await self._send_with_single_reply(
            job.OP_ANALYSIS,
            req,
            jobProcessCmd='get_data_file'
        )

    async def _receive_api_runCancel(self, req):
        async def _reply_canceled(self, req):
            return PKDict(state=job.CANCELED)

        async def _cancel_queued(self, req):
            for o in self._ops:
                if o.msg.computeJid == req.content.computeJid:
                    o.set_canceled()
            return await _reply_canceled(self, req)

        async def _cancel_running(self, req):
            o = await self._send_with_single_reply(
                job.OP_CANCEL,
                req,
            )
            assert o.state == job.CANCELED
            return await _reply_canceled(self, req)

        if self.db.computeJobHash == req.content.computeJobHash:
#TODO(robnagler) not sure a state table works all that well here.
#    if statements seem appropriate.

            d = PKDict({
                job.CANCELED: _reply_canceled,
                job.COMPLETED: _reply_canceled,
                job.ERROR: _reply_canceled,
                job.MISSING: _reply_canceled,
                job.PENDING: _cancel_queued,
                job.RUNNING: _cancel_running,
            })
#TODO(robnagler) why does this not need to be an await
            r = d[self.db.status](self, req)
#TODO(robnagler) at this point we don't know anything so
#  we are canceling something we need to validate the state
# of.
            self.db.status = job.CANCELED
            self.__db_write()
            return await r
#TODO(robnagler) this is always true, because the previous
# if was false.
        if self.db.computeJobHash != req.content.computeJobHash:
            self.db.status = job.CANCELED
            self.__db_write()
            return await _cancel_queued(self, req)

    async def _receive_api_runSimulation(self, req):
        if self.db.status == _RUNNING_PENDING:
            if self.db.computeJobHash != req.content.computeJobHash:
#TODO(robnagler) need to deal with double clicks
#TODO(robnagler) do transient/sequential sims runSim without a cancel? I think we
#  should require the GUI to cancel before running so would return an error here
                raise AssertionError('FIXME')
            return PKDict(state=job.RUNNING)
        if (self.db.computeJobHash != req.content.computeJobHash
            or self.db.status != job.COMPLETED
        ):
            self.__db_init(req, prev=self.db)
            self.db.jobRunMode
            self.db.pkupdate(
                status=job.PENDING,
                computeJobStart=int(time.time()),
            )
            if self.db.isParallel:
                self.db.parallelStatus.pkupdate(
                    computeJobStart=self.db.computeJobStart,
                    lastUpdateTime=self.db.computeJobStart,
                )
            self.__db_write()
            tornado.ioloop.IOLoop.current().add_callback(self._run, req)
        # Read this first https://github.com/radiasoft/sirepo/issues/2007
        return await self._receive_api_runStatus(req)

    async def _receive_api_runStatus(self, req):
        def res(**kwargs):
            r = PKDict(**kwargs)
            if self.db.error:
                r.error = self.db.error
            if self.db.isParallel:
                r.update(**self.db.parallelStatus)
                r.elapsedTime = r.lastUpdateTime - r.computeJobStart
                r.computeJobHash = self.db.computeJobHash
            if self.db.status in _RUNNING_PENDING:
                c = req.content
                r.update(
                    nextRequestSeconds=self.db.nextRequestSeconds,
                    nextRequest=PKDict(
                        report=c.analysisModel,
                        computeJobHash=self.db.computeJobHash,
                        simulationId=self.db.simulationId,
                        simulationType=self.db.simulationType,
                    ),
                )
            return r
        if self.db.computeJobHash != req.content.computeJobHash:
            return res(state=job.MISSING)
        if self.db.isParallel or self.db.status != job.COMPLETED:
            return res(state=self.db.status)
        return await self._send_with_single_reply(
            job.OP_ANALYSIS,
            req,
            jobProcessCmd='sequential_result'
        )

    async def _receive_api_simulationFrame(self, req):
        assert self.db.computeJobHash == req.content.computeJobHash
        return await self._send_with_single_reply(
            job.OP_ANALYSIS,
            req,
            'get_simulation_frame'
        )

    async def _run(self, req):
        if self.db.computeJobHash != req.content.computeJobHash:
            pkdlog(
                'invalid computeJobHash self={} req={}',
                self.db.computeJobHash,
                req.content.computeJobHash
            )
            return
        o = await self._send(
            job.OP_RUN,
            req,
            jobProcessCmd='compute'
        )
        # TODO(e-carlin): XXX bug. If cancel comes in then self.db.status = canceled
        # This overwrites it, but there is a state=canceled message waiting for
        # us in the reply_ready q. We then await o.reply_ready() and get the cancel
        # message then set self.db.status back to canceled. This works because the
        # await o.reply_ready() doesn't block because there is a cancel message
        # in the q
#TODO(robnagler) should this not check the state when it comes out of _send()?
# if it's canceled, then don't run. It should only be PENDING in this state.
# We talked about reusing status for two purposes: job status and driver queue state.
# The two probably needed to be separated. status stays pending until the driver (sbatch)
# says it is running. driver-wise we have "sent run", not "running"
        self.db.status = job.RUNNING
        self.__db_write()
        while True:
            r = await o.reply_ready()
            self.db.status = r.state
            if self.db.status == job.ERROR:
                self.db.error = r.get('error', '<unknown error>')
            if 'parallelStatus' in r:
                assert self.db.isParallel
                self.db.parallelStatus.update(r.parallelStatus)
                #TODO(robnagler) will need final frame count
            # TODO(e-carlin): What if this never comes?
            if 'opDone' in r:
                break
        self.destroy_op(o)
        self.__db_write()

    async def _send(self, opName, req, jobProcessCmd):
        # TODO(e-carlin): proper error handling
        try:
#TODO(robnagler) kind should be set earlier in the queuing process.
            req.kind = job.PARALLEL if self.db.isParallel and opName != job.OP_ANALYSIS \
                else job.SEQUENTIAL
            req.simulationType = self.db.simulationType
            # TODO(e-carlin): We need to be able to cancel requests waiting in this
            # state. Currently we assume that all requests get a driver and the
            # code does not block.
            d = await job_driver.get_instance(req, self.db.jobRunMode)
            o = _Op(
                driver=d,
                msg=PKDict(
                    jobProcessCmd=jobProcessCmd,
                    **req.content,
                ),
                opName=opName,
            )
            self._ops.append(o)
            await d.send(o)
            return o
        except Exception as e:
            pkdlog('error={} stack={}', e, pkdexc())

    async def _send_with_single_reply(self, opName, req, jobProcessCmd=None):
        o = await self._send(opName, req, jobProcessCmd)
        r = await o.reply_ready()
        assert 'opDone' in r
        self.destroy_op(o)
        return r


class _Op(PKDict):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update(
            opId=job.unique_key(),
            send_ready=tornado.locks.Event(),
            canceled=False,
            errored=False,
            _reply_q=tornado.queues.Queue(),
        )
        self.msg.update(opId=self.opId, opName=self.opName)

    def set_canceled(self):
        self.canceled = True
        self.reply_put(PKDict(state=job.CANCELED, opDone=True))
        self.send_ready.set()
        self.driver.cancel_op(self)

    def set_errored(self, error):
        self.errored = True
        self.reply_put(
            PKDict(state=job.ERROR, error=error, opDone=True),
        )
        self.send_ready.set()

    def destroy(self):
        self.driver.destroy_op(self)

    def reply_put(self, msg):
        self._reply_q.put_nowait(msg)

    async def reply_ready(self):
        r = await self._reply_q.get()
        self._reply_q.task_done()
        return r
