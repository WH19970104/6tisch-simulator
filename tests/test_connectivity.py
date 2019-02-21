"""
Tests for SimEngine.Connectivity
"""
import datetime as dt
import itertools
import json
import gzip
import os
import random
import shutil
import types

from scipy.stats import t
from numpy import average, std
from math import sqrt
import pytest
import k7

import test_utils as u
import SimEngine.Mote.MoteDefines as d
from SimEngine import SimLog
from SimEngine.SimConfig import SimConfig
from SimEngine.Connectivity import Connectivity, ConnectivityMatrixBase

#============================ helpers =========================================

def destroy_all_singletons(engine):
    engine.destroy()
    engine.connectivity.destroy()
    engine.settings.destroy()
    SimLog.SimLog().destroy()

#============================ tests ===========================================

def test_linear_matrix(sim_engine):
    """ verify the connectivity matrix for the 'Linear' class is as expected

    creates a static connectivity linear path
    0 <-- 1 <-- 2 <-- ... <-- num_motes
    """

    num_motes = 6
    engine = sim_engine(
        diff_config = {
            'exec_numMotes': num_motes,
            'conn_class':    'Linear',
        }
    )
    motes  = engine.motes
    matrix = engine.connectivity.matrix

    matrix.dump()

    assert motes[0].dagRoot is True

    for c in range(0, num_motes):
        for p in range(0, num_motes):
            if (c == p+1) or (c+1 == p):
                for channel in d.TSCH_HOPPING_SEQUENCE:
                    assert matrix.get_pdr(c, p, channel)  ==  1.00
                    assert matrix.get_rssi(c, p, channel) ==   -10
            else:
                for channel in d.TSCH_HOPPING_SEQUENCE:
                    assert matrix.get_pdr(c, p, channel)  ==  0.00
                    assert matrix.get_rssi(c, p, channel) == -1000

class TestK7(object):
    TRACE_FILE_PATH = os.path.join(
        os.path.dirname(__file__),
        '../traces/grenoble.k7.gz'
    )

    @property
    def header(self):
        with gzip.open(self.TRACE_FILE_PATH, 'r') as tracefile:
            return json.loads(tracefile.readline())

    @property
    def num_motes(self):
        return self.header['node_count']

    @property
    def channels(self):
        return self.header['channels']

    @property
    def trace_duration(self):
        start_time = dt.datetime.strptime(
            self.header['start_date'],
            "%Y-%m-%d %H:%M:%S"
        )
        stop_time = dt.datetime.strptime(
            self.header['stop_date'],
            "%Y-%m-%d %H:%M:%S"
        )
        return (stop_time - start_time).total_seconds()

    def test_free_run(self, sim_engine):
        """ verify the connectivity matrix for the 'K7' class is as expected """



        engine = sim_engine(
            diff_config = {
                'exec_numMotes': self.num_motes,
                'conn_class'   : 'K7',
                'conn_trace'   : self.TRACE_FILE_PATH,
                'phy_numChans' : len(self.channels)
            }
        )
        motes  = engine.motes
        matrix = engine.connectivity.matrix

        matrix.dump()

        assert motes[0].dagRoot is True

        for src in range(0, self.num_motes):
            for dst in range(0, self.num_motes):
                if src == dst:
                    continue
                for channel in d.TSCH_HOPPING_SEQUENCE:
                    pdr = matrix.get_pdr(src, dst, channel)
                    rssi = matrix.get_rssi(src, dst, channel)
                    assert isinstance(pdr, (int, long, float))
                    assert isinstance(rssi, (int, long, float))
                    assert 0 <= pdr <= 1
                    assert ConnectivityMatrixBase.LINK_NONE['rssi'] <= rssi <= 0


    @pytest.fixture(params=['short', 'equal', 'long'])
    def fixture_test_type(self, request):
        return request.param

    def test_simulation_time(self, sim_engine, fixture_test_type):
        tsch_slotDuration = 0.010
        numSlotframes = self.trace_duration / tsch_slotDuration

        if fixture_test_type == 'short':
            numSlotframes -= 1
        elif fixture_test_type == 'equal':
            pass
        elif fixture_test_type == 'long':
            numSlotframes += 1
        else:
            raise NotImplementedError()

        diff_config = {
            'exec_numSlotframesPerRun': numSlotframes,
            'exec_numMotes'           : self.num_motes,
            'conn_class'              : 'K7',
            'conn_trace'              : self.TRACE_FILE_PATH,
            'tsch_slotDuration'       : tsch_slotDuration
        }

        if fixture_test_type == 'long':
            with pytest.raises(ValueError):
                sim_engine(diff_config=diff_config)
            # destroy the ConnectivityK7 instance
            connectivity = Connectivity()
            connectivity.destroy()
        else:
            sim_engine(diff_config=diff_config)

    @pytest.fixture(params=[
        'exact_match',
        'all_covered',
        'partly_covered',
        'not_covered'
    ])
    def fixture_channels_coverage_type(self, request):
        return request.param

    def test_check_channels_in_header(
            self,
            sim_engine,
            fixture_channels_coverage_type
        ):
        channels_in_header = self.header['channels']
        assert channels_in_header

        tsch_hoppping_sequence_backup = d.TSCH_HOPPING_SEQUENCE
        d.TSCH_HOPPING_SEQUENCE = channels_in_header[:]
        if fixture_channels_coverage_type == 'exact_match':
            # do nothing
            pass
        elif fixture_channels_coverage_type == 'all_covered':
            # remove the first channel in the sequence
            d.TSCH_HOPPING_SEQUENCE.pop(0)
        elif fixture_channels_coverage_type == 'partly_covered':
            # add an invalid channel, which never be listed in the
            # header
            d.TSCH_HOPPING_SEQUENCE.append(-1)
        elif fixture_channels_coverage_type == 'not_covered':
            # put different channels to the hopping sequence from the ones
            # listed in the header
            d.TSCH_HOPPING_SEQUENCE = map(lambda x: x + 10, channels_in_header)
        else:
            raise NotImplementedError()

        diff_config = {
            'exec_numMotes': self.num_motes,
            'conn_class': 'K7',
            'conn_trace': self.TRACE_FILE_PATH,
            'phy_numChans': len(d.TSCH_HOPPING_SEQUENCE)
        }
        if fixture_channels_coverage_type in ['partly_covered', 'not_covered']:
            with pytest.raises(ValueError):
                sim_engine(diff_config=diff_config)
            connectivity = Connectivity()
            connectivity.destroy()
        else:
            sim_engine(diff_config=diff_config)

        d.TSCH_HOPPING_SEQUENCE = tsch_hoppping_sequence_backup

#=== verify propagate function doesn't raise exception

def test_propagate(sim_engine):
    engine = sim_engine()
    engine.connectivity.propagate()


#=== test for ConnectivityRandom
class TestRandom(object):

    def test_free_run(self, sim_engine):
        # all the motes should be able to join the network
        sim_engine = sim_engine(
            diff_config = {
                'exec_numSlotframesPerRun'      : 10000,
                'conn_class'                    : 'Random',
                'secjoin_enabled'               : False,
                "phy_numChans"                  : 1,
            }
        )
        asn_at_end_of_simulation = (
            sim_engine.settings.tsch_slotframeLength *
            sim_engine.settings.exec_numSlotframesPerRun
        )

        u.run_until_everyone_joined(sim_engine)
        assert sim_engine.getAsn() < asn_at_end_of_simulation

    def test_getter(self, sim_engine):
        num_channels = 2
        sim_engine = sim_engine(
            diff_config = {
                'conn_class'                    : 'Random',
                'exec_numMotes'                 : 2,
                'conn_random_init_min_neighbors': 1,
                'phy_numChans'                  : num_channels,
            }
        )

        # PDR and RSSI should not change over time
        for src, dst in zip(sim_engine.motes[:-1], sim_engine.motes[1:]):
            for channel in d.TSCH_HOPPING_SEQUENCE[:num_channels]:
                pdr  = []
                rssi = []

                for _ in range(100):
                    pdr.append(
                        sim_engine.connectivity.get_pdr(
                            src_id  = src.id,
                            dst_id  = dst.id,
                            channel = channel
                        )
                    )
                    rssi.append(
                        sim_engine.connectivity.get_rssi(
                            src_id  = src.id,
                            dst_id  = dst.id,
                            channel = channel
                        )
                    )
                    # proceed the simulator
                    u.run_until_asn(sim_engine, sim_engine.getAsn() + 1)

                # compare two consecutive PDRs and RSSIs. They should be always
                # the same value. Then, the following condition of 'i != j'
                # should always false
                assert sum([(i != j) for i, j in zip(pdr[:-1], pdr[1:])])   == 0
                assert sum([(i != j) for i, j in zip(rssi[:-1], rssi[1:])]) == 0

        # PDR and RSSI should be the same within the same slot, of course
        for src, dst in zip(sim_engine.motes[:-1], sim_engine.motes[1:]):
            for channel in d.TSCH_HOPPING_SEQUENCE[:num_channels]:
                pdr  = []
                rssi = []

                for _ in range(100):
                    pdr.append(
                        sim_engine.connectivity.get_pdr(
                            src_id  = src.id,
                            dst_id  = dst.id,
                            channel = channel
                        )
                    )
                    rssi.append(
                        sim_engine.connectivity.get_rssi(
                            src_id  = src.id,
                            dst_id  = dst.id,
                            channel = channel
                        )
                    )

                # compare two consecutive PDRs and RSSIs; all the pairs should
                # be same (all comparison, i != j, should be False).
                assert sum([(i != j) for i, j in zip(pdr[:-1], pdr[1:])])   == 0
                assert sum([(i != j) for i, j in zip(rssi[:-1], rssi[1:])]) == 0


    def test_context_random_seed(self, sim_engine):
        diff_config = {
            'exec_numMotes'  : 10,
            'exec_randomSeed': 'context',
            'conn_class'     : 'Random'
        }

        # ConnectivityRandom should create an identical topology for two
        # simulations having the same run_id
        sf_class_list = ['SFNone', 'MSF']
        coordinates = {}
        for sf_class, run_id in itertools.product(sf_class_list, [1, 2]):
            diff_config['sf_class'] = sf_class
            engine = sim_engine(
                diff_config                                = diff_config,
                force_initial_routing_and_scheduling_state = False,
                run_id                                     = run_id
            )
            coordinates[(sf_class, run_id)] = (
                engine.connectivity.matrix.coordinates
            )
            destroy_all_singletons(engine)

        # We have four sets of coordinates:
        # - coordinates of ('SFNone', run_id=1) and ('MSF',    1) should be
        #   identical
        # - coordinates of ('SFNone', run_id=2) and ('MSF',    2) should be
        #   identical
        # - coordinates of ('SFNone,  run_id=1) and ('SFNone', 2) should be
        #   different
        # - coordinates of ('MSF',    run_id=1) and ('MSF',    2) should be
        #   different
        assert coordinates[('SFNone', 1)] == coordinates[('MSF', 1)]
        assert coordinates[('SFNone', 2)] == coordinates[('MSF', 2)]
        assert coordinates[('SFNone', 1)] != coordinates[('SFNone', 2)]
        assert coordinates[('MSF', 1)]    != coordinates[('MSF', 2)]

#=== test for LockOn mechanism that is implemented in propagate()
def test_lockon(sim_engine):
    sim_engine = sim_engine(
        diff_config = {
            'exec_numMotes'           : 2,
            'exec_numSlotframesPerRun': 1,
            'conn_class'              : 'Linear',
            'app_pkPeriod'            : 0,
            'secjoin_enabled'         : False,
            'sf_class'                : 'SFNone',
            'tsch_probBcast_ebProb'   : 0,
            'rpl_daoPeriod'           : 0
        }
    )

    # short-hands
    root  = sim_engine.motes[0]
    hop_1 = sim_engine.motes[1]

    # force hop_1 to join the network
    eb = root.tsch._create_EB()
    hop_1.tsch._action_receiveEB(eb)
    dio = root.rpl._create_DIO()
    dio['mac'] = {'srcMac': root.get_mac_addr()}
    hop_1.rpl.action_receiveDIO(dio)

    # let hop_1 send an application packet
    hop_1.app._send_a_single_packet()

    # force random.random() to return 1, which will cause any frame not to be
    # received by anyone
    _random = random.random
    def return_one(self):
        return float(1)
    random.random = types.MethodType(return_one, random)

    # run the simulation
    u.run_until_end(sim_engine)

    # put the original random() back to random
    random.random = _random

    # root shouldn't lock on the frame hop_1 sent since root is not expected to
    # receive even the preamble of the packet.
    logs = u.read_log_file([SimLog.LOG_PROP_DROP_LOCKON['type']])
    assert len(logs) == 0

#=== test if the simulator ends without an error

ROOT_DIR        = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
TRACE_FILE_PATH = os.path.join(ROOT_DIR, 'traces/grenoble.k7.gz')

@pytest.fixture(params=['FullyMeshed', 'Linear', 'K7', 'Random'])
def fixture_conn_class(request):
    return request.param

def test_runsim(sim_engine, fixture_conn_class):
    # run the simulation with each conn_class. use a shorter
    # 'exec_numSlotframesPerRun' so that this test doesn't take long time
    diff_config = {
        'exec_numSlotframesPerRun': 100,
        'conn_class'              : fixture_conn_class
    }
    if fixture_conn_class == 'K7':
        with gzip.open(TRACE_FILE_PATH, 'r') as trace:
            header = json.loads(trace.readline())
            diff_config['exec_numMotes'] = header['node_count']
        diff_config['conn_trace'] = TRACE_FILE_PATH

    sim_engine = sim_engine(diff_config=diff_config)
    u.run_until_end(sim_engine)
