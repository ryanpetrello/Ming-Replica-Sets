from __future__ import with_statement
import time
import logging

from threading import Lock

from pymongo.connection import Connection
from pymongo.master_slave_connection import MasterSlaveConnection

from .utils import parse_uri
from . import mim

log = logging.getLogger(__name__)

class DataStore(object):
    """Manages a connections to Mongo, with seprate connections per thread."""

    def __init__(self, master='mongo://localhost:27017/gutenberg', slave=None,
                 connect_retry=3):
        # self._tl_value = ThreadLocal()
        self._conn = None
        self._lock = Lock()
        self._connect_retry = connect_retry
        self.configure(master, slave)

    def __repr__(self):
        return 'DataStore(master=%r, slave=%r)' % (
            self.master_args, self.slave_args)

    def configure(self, master='mongo://localhost:27017/gutenberg', slave=None):
        log.disabled = 0 # @%#$@ logging fileconfig disables our logger
        if isinstance(master, basestring):
            master = [ master ]
        if isinstance(slave, basestring):
            slave = [ slave ]
        if master is None: master = []
        if slave is None: slave = []
        self.master_args = [ parse_uri(s) for s in master if s ]
        self.slave_args = [ parse_uri(s) for s in slave if s ]
        if len(self.master_args) > 2:
            log.warning(
                'Only two masters are supported at present, you specified %r',
                master)
            self.master_args = self.master_args[:2]
        if len(self.master_args) > 1 and self.slave_args:
            log.warning(
                'Master/slave is not supported with replica pairs')
            self.slave_args = []
        one_url = (self.master_args+self.slave_args)[0]
        self.database = one_url['path'][1:]
        self.scheme = one_url['scheme']
        if one_url['scheme'] == 'mim':
            self._conn = mim.Connection.get()
        for a in self.master_args + self.slave_args:
            assert a['scheme'] == self.scheme
            assert a['path'] == '/' + self.database, \
                "All connections MUST use the same database"

    @property
    def conn(self):
        for attempt in xrange(self._connect_retry+1):
            if self._conn is not None: break
            with self._lock:
                if self._connect() is None:
                    time.sleep(1)
        return self._conn

    def _connect(self):
        self._conn = None
        try:
            if len(self.master_args) == 2:
                self._conn = Connection.paired(
                    (str(self.master_args[0]['host']), int(self.master_args[0]['port'])),
                    (str(self.master_args[1]['host']), int(self.master_args[1]['port'])))
            else:
                if self.master_args:
                    try:
                        network_timeout = self.master_args[0]['query'].get('network_timeout')
                        if network_timeout is not None:
                            network_timeout = float(network_timeout)
                        master = Connection(str(self.master_args[0]['host']), int(self.master_args[0]['port']),
                                            network_timeout=network_timeout)
                    except:
                        if self.slave_args:
                            log.exception('Cannot connect to master: %s will use slave: %s' % (self.master_args, self.slave_args))
                            # and continue... to use the slave only
                            master = None
                        else:
                            raise
                else:
                    log.info('No master connection specified, using slaves only: %s' % self.slave_args)
                    master = None

                if self.slave_args:
                    slave = []
                    for a in self.slave_args:
                        network_timeout = a['query'].get('network_timeout')
                        if network_timeout is not None:
                            network_timeout = float(network_timeout)
                        slave.append(
                            Connection(str(a['host']), int(a['port']),
                                       slave_okay=True,
                                       network_timeout=network_timeout,
                                      )
                        )
                    if master:
                        self._conn = MasterSlaveConnection(master, slave)
                    else:
                        self._conn = slave[0]

                else:
                    self._conn = master
        except:
            log.exception('Cannot connect to %s %s' % (self.master_args, self.slave_args))
        else:
            #log.info('Connected to %s %s' % (self.master_args, self.slave_args))
            pass
        return self._conn

    @property
    def db(self):
        return getattr(self.conn, self.database, None)

class ReplicaSetDataStore(DataStore):

    def __init__(self, members=['mongo://localhost:27017/gutenberg'], connect_retry=3):
        # self._tl_value = ThreadLocal()
        self._conn = None
        self._lock = Lock()
        self._connect_retry = connect_retry
        self.configure(members)

    def __repr__(self):
        return 'ReplicaSetDataStore(members=%r)' % (self.members)

    def configure(self, members=['mongo://localhost:27017/gutenberg']):
        log.disabled = 0 # @%#$@ logging fileconfig disables our logger
        if members is None: members = []
        self.members = [ parse_uri(s) for s in members if s ]
        one_url = self.members[0]
        self.database = one_url['path'][1:]
        self.scheme = one_url['scheme']
        if not len(self.members):
            log.warning(
                'At least one member is required for a replica set, you specified none')
        if one_url['scheme'] == 'mim':
            self._conn = mim.Connection.get()
        for a in self.members:
            assert a['scheme'] == self.scheme
            assert a['path'] == '/' + self.database, \
                "All connections MUST use the same database"

    def _connect(self):
        self._conn = None
        try:
            if len(self.members):
                network_timeout = self.members[0]['query'].get('network_timeout')
                if network_timeout is not None:
                    network_timeout = float(network_timeout)                
                self._conn = Connection(
                    map(lambda x: '%s:%s' % (x.get('host'), x.get('port')), self.members),
                    network_timeout=network_timeout
                )
        except:
            log.exception('Cannot connect to any members %r' % (self.members))
        return self._conn