#!/usr/bin/python
"""
\brief Discrete-event simulation engine.

\author Thomas Watteyne <watteyne@eecs.berkeley.edu>
\author Kazushi Muraoka <k-muraoka@eecs.berkeley.edu>
\author Nicola Accettura <nicola.accettura@eecs.berkeley.edu>
\author Xavier Vilajosana <xvilajosana@eecs.berkeley.edu>
"""

#============================ logging =========================================

import logging
class NullHandler(logging.Handler):
    def emit(self, record):
        pass
log = logging.getLogger('SimEngine')
log.setLevel(logging.ERROR)
log.addHandler(NullHandler())

#============================ imports =========================================

import threading

from Propagation import Propagation
import Topology
import Mote
import SimSettings
import sf

#============================ defines =========================================

#============================ body ============================================

class SimEngine(threading.Thread):

    #===== start singleton
    _instance      = None
    _init          = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(SimEngine,cls).__new__(cls, *args, **kwargs)
        return cls._instance
    #===== end singleton

    def __init__(self, cpuID=None, runNum=None, failIfNotInit=False):

        if failIfNotInit and not self._init:
            raise EnvironmentError('SimEngine singleton not initialized.')

        #===== start singleton
        if self._init:
            return
        self._init = True
        #===== end singleton

        # store params
        self.cpuID                          = cpuID
        self.runNum                         = runNum

        # local variables
        self.dataLock                       = threading.RLock()
        self.pauseSem                       = threading.Semaphore(0)
        self.simPaused                      = False
        self.goOn                           = True
        self.asn                            = 0
        self.startCb                        = []
        self.endCb                          = []
        self.events                         = []

        # init singletons
        self.settings                       = SimSettings.SimSettings()
        self.propagation                    = Propagation()
        if hasattr(self.settings, 'numMotes'):
            self.motes                      = [Mote.Mote(id) for id in range(self.settings.numMotes)]
        elif self.propagation.type == 'trace':
            self.motes                      = [Mote.Mote(id) for id in range(self.propagation.num_motes)]
            # TODO load the trace earlier and fill the engine setting from the trace
        else:
            raise AttributeError(self.propagation.type)
        self.topology                       = Topology.Topology(self.motes)
        self.topology.createTopology()

        # init schedule
        sf.init(self.topology, self.settings.sf_type)

        # boot all motes
        for i in range(len(self.motes)):
            self.motes[i].boot()

        # initialize parent class
        threading.Thread.__init__(self)
        self.name                           = 'SimEngine'

    def destroy(self):
        # destroy the propagation singleton
        self.propagation.destroy()

        # destroy my own instance
        self._instance                      = None
        self._init                          = False
        del self.__dict__

    #======================== thread ==========================================

    def run(self):
        """ event driven simulator, this thread manages the events """

        # log
        log.info("thread {0} starting".format(self.name))

        # schedule the endOfSimulation event if we are not simulating the join process
        if not self.settings.secjoin_enabled:
            self.scheduleAtAsn(
                asn         = self.settings.slotframeLength*self.settings.exec_numSlotframesPerRun,
                cb          = self._actionEndSim,
                uniqueTag   = (None,'_actionEndSim'),
            )

        # call the start callbacks
        for cb in self.startCb:
            cb()

        # consume events until self.goOn is False
        while self.goOn:

            with self.dataLock:

                # abort simulation when no more events
                if not self.events:
                    log.info("end of simulation at ASN={0}".format(self.asn))
                    break

                # make sure we are in the future
                (a, b, cb, c, kwargs) = self.events[0]
                if c[1] != '_actionPauseSim':
                    assert self.events[0][0] >= self.asn

                # update the current ASN
                self.asn = self.events[0][0]

                # call callbacks at this ASN
                while True:
                    if self.events[0][0] != self.asn:
                        break
                    (_, _, cb, _, kwargs) = self.events.pop(0)
                    cb(**kwargs)

        # call the end callbacks
        for cb in self.endCb:
            cb()

        # log
        log.info("thread {0} ends".format(self.name))

    #======================== public ==========================================

    #=== scheduling

    def scheduleAtStart(self,cb):
        with self.dataLock:
            self.startCb    += [cb]

    def scheduleIn(self, delay, cb, uniqueTag=None, priority=0, exceptCurrentASN=True, kwargs={}):
        """ used to generate events. Puts an event to the queue """

        with self.dataLock:
            asn = int(self.asn + (float(delay) / float(self.settings.slotDuration)))

            self.scheduleAtAsn(asn, cb, uniqueTag, priority, exceptCurrentASN, kwargs)

    def scheduleAtAsn(self, asn, cb, uniqueTag=None, priority=0, exceptCurrentASN=True, kwargs={}):
        """ schedule an event at specific ASN """

        # make sure we are scheduling in the future
        assert asn > self.asn

        # remove all events with same uniqueTag (the event will be rescheduled)
        if uniqueTag:
            self.removeEvent(uniqueTag, exceptCurrentASN)

        with self.dataLock:

            # find correct index in schedule
            i = 0
            while i<len(self.events) and (self.events[i][0] < asn or (self.events[i][0] == asn and self.events[i][1] <= priority)):
                i +=1

            # add to schedule
            self.events.insert(i, (asn, priority, cb, uniqueTag, kwargs))

    def removeEvent(self, uniqueTag, exceptCurrentASN=True):
        with self.dataLock:
            i = 0
            while i<len(self.events):
                if self.events[i][3]==uniqueTag and not (exceptCurrentASN and self.events[i][0]==self.asn):
                    self.events.pop(i)
                else:
                    i += 1

    def scheduleAtEnd(self,cb):
        with self.dataLock:
            self.endCb      += [cb]

    # === misc

    #delay in asn
    def terminateSimulation(self,delay):
        self.asnEndExperiment=self.asn+delay
        self.scheduleAtAsn(
                asn         = self.asn+delay,
                cb          = self._actionEndSim,
                uniqueTag   = (None,'_actionEndSim'),
        )

    #=== play/pause

    def play(self):
        self._actionResumeSim()

    def pauseAtAsn(self,asn):
        if not self.simPaused:
            self.scheduleAtAsn(
                asn         = asn,
                cb          = self._actionPauseSim,
                uniqueTag   = ('SimEngine','_actionPauseSim'),
            )

    #=== getters/setters

    def getAsn(self):
        return self.asn

    #======================== private =========================================

    def _actionPauseSim(self):
        if not self.simPaused:
            self.simPaused = True
            self.pauseSem.acquire()

    def _actionResumeSim(self):
        if self.simPaused:
            self.simPaused = False
            self.pauseSem.release()

    def _actionEndSim(self):
        with self.dataLock:
            self.goOn = False
