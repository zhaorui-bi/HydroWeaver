"""Fake WaterTAP/IDAES/Pyomo modules for the simulation runner tests.

The fakes model only the API surface the runner touches, in the call order the
runner uses it, so a change in the runner's orchestration fails a test instead
of silently producing a wrong flowsheet.
"""

FAKE_PYOMO = '''
    class _Var:
        def __init__(self, name='var'):
            self.name = name
            self.value = None
            self.fixed = False

        def __sub__(self, other):
            return _Expr(self, other)

        def __rsub__(self, other):
            return _Expr(self, other)

        def __pow__(self, other):
            return _Expr(self, other)

        def fix(self, value):
            self.value = value
            self.fixed = True

        def unfix(self):
            self.fixed = False

        def setlb(self, value):
            self.lb = value

        def setub(self, value):
            self.ub = value


    class _Expr:
        def __init__(self, left, right):
            self.left = left
            self.right = right

        def __pow__(self, other):
            return _Expr(self, other)


    class _Indexed(dict):
        """Pyomo-like indexed container: item assignment sets the variable value."""

        def __missing__(self, key):
            if isinstance(key, tuple):
                var = _Var()
                dict.__setitem__(self, key, var)
                return var
            raise KeyError(key)

        def __setitem__(self, key, value):
            if isinstance(value, _Var):
                dict.__setitem__(self, key, value)
                return
            if key not in self:
                dict.__setitem__(self, key, _Var())
            self[key].value = value


    class _State:
        def __init__(self):
            self.pressure = _Var('pressure')
            self.temperature = _Var('temperature')
            self.flow_mass_phase_comp = _Indexed({
                ('Liq', 'H2O'): _Var('H2O'),
                ('Liq', 'NaCl'): _Var('NaCl'),
            })
            self.conc_mass_phase_comp = _Indexed()


    class _Port:
        def __init__(self):
            self.properties = _State()

        @property
        def pressure(self):
            return _PortState(self, 'pressure')

        @property
        def temperature(self):
            return _PortState(self, 'temperature')

        @property
        def flow_mass_phase_comp(self):
            return _PortIndexed(self, 'flow_mass_phase_comp')

        @property
        def conc_mass_phase_comp(self):
            return _PortIndexed(self, 'conc_mass_phase_comp')


    class _PortState:
        def __init__(self, port, name):
            self.port = port
            self.name = name

        def __getitem__(self, index):
            return getattr(self.port.properties, self.name)

        @property
        def value(self):
            return getattr(self.port.properties, self.name).value


    class _PortIndexed:
        def __init__(self, port, name):
            self.port = port
            self.name = name

        def __getitem__(self, key):
            return getattr(self.port.properties, self.name)[key[-2:]]


    class _Objective:
        def __init__(self, expr=None):
            self.expr = expr


    class Constraint:
        pass


    class Objective:
        def __init__(self, expr=None):
            import pyomo.environ as _ev
            _ev.EVENTS.append(('objective', expr))


    def value(item):
        if hasattr(item, 'value'):
            return item.value
        return item


    class Arc:
        def __init__(self, source=None, destination=None):
            import pyomo.environ as _ev
            _ev.EVENTS.append(('arc', source, destination))


    class _Transformation:
        def apply_to(self, model):
            import pyomo.environ as _ev
            _ev.EVENTS.append(('expand_arcs', model))


    def TransformationFactory(name):
        return _Transformation()


    class ConcreteModel:
        def __init__(self):
            pass


    EVENTS = []
'''

FAKE_IDAES = '''
    class FlowsheetBlock:
        def __init__(self, dynamic=False):
            self.dynamic = dynamic


    class _Status:
        status = 'ok'
        termination_condition = 'optimal'
        message = 'fixture optimal'


    class _Results:
        def __init__(self):
            self.solver = _Status()


    class _Solver:
        options = {}

        def solve(self, model, tee=False):
            import pyomo.environ as _ev
            _ev.EVENTS.append(('solve', model))
            return _Results()


    def get_solver(*args, **kwargs):
        return _Solver()
'''

FAKE_IDAES_UTIL = '''
    def set_scaling_factor(component, factor):
        import pyomo.environ as _ev
        _ev.EVENTS.append(('scaling', component, factor))


    def calculate_scaling_factors(model):
        import pyomo.environ as _ev
        _ev.EVENTS.append(('calculate_scaling', model))


    def degrees_of_freedom(model):
        return 0


    def propagate_state(arc):
        import pyomo.environ as _ev
        _ev.EVENTS.append(('propagate', arc))
'''

FAKE_IDAES_MODELS = '''
    from pyomo.environ import _Block


    class Feed(_Block):
        def __init__(self, property_package=None, **kwargs):
            import pyomo.environ as _pe
            super().__init__()
            _pe.EVENTS.append(('unit', 'Feed'))

        def initialize(self, optarg=None, **kwargs):
            import pyomo.environ as _ev
            _ev.EVENTS.append(('initialize', 'Feed', kwargs))
'''

FAKE_WATERTAP_SOLVERS = '''
    def get_solver(*args, **kwargs):
        from idaes.core.solvers import get_solver as _get
        return _get()
'''

FAKE_WATERTAP_UNIT_MODELS = '''
    def calculate_operating_pressure(state_block=None, over_pressure_factor=1.15, water_recovery_mass=0.5, salt_passage=0, solver=None):
        import pyomo.environ as _ev
        _ev.EVENTS.append(('operating_pressure', water_recovery_mass))
        return 1.2e6
'''

FAKE_PRESSURE_CHANGER = '''
    from pyomo.environ import _Block


    class Pump(_Block):
        def __init__(self, property_package=None, **kwargs):
            super().__init__()
            self.control_volume.properties_out[0].pressure.fix(0.0)
            import pyomo.environ as _ev
            _ev.EVENTS.append(('unit', 'Pump'))

        def initialize(self, optarg=None, **kwargs):
            import pyomo.environ as _ev
            _ev.EVENTS.append(('initialize', 'Pump', kwargs))
'''

FAKE_RO_0D = '''
    from enum import Enum

    from pyomo.environ import _Block


    class PressureChangeType(Enum):
        calculated = 'calculated'
        fixed_per_stage = 'fixed_per_stage'


    class MassTransferCoefficient(Enum):
        calculated = 'calculated'
        none = 'none'


    class ConcentrationPolarizationType(Enum):
        calculated = 'calculated'
        fixed = 'fixed'


    class ReverseOsmosis0D(_Block):
        def __init__(self, property_package=None, has_pressure_change=False, **kwargs):
            super().__init__()
            self.feed_side.properties_in[0].pressure.fix(0.0)
            import pyomo.environ as _ev
            _ev.EVENTS.append(('unit', 'ReverseOsmosis0D', dict(has_pressure_change=has_pressure_change, **kwargs)))

        def initialize(self, optarg=None, initialization_degrees_of_freedom=0, **kwargs):
            import pyomo.environ as _ev
            _ev.EVENTS.append(('initialize', 'RO', {'dof': initialization_degrees_of_freedom}))
            self.feed_side.properties[0, 0].flow_mass_phase_comp['Liq', 'H2O'].value = 0.5
            self.mixed_permeate[0].flow_mass_phase_comp['Liq', 'H2O'].value = 0.25
            self.mixed_permeate[0].conc_mass_phase_comp['Liq', 'NaCl'].value = 0.00008
            self.area.value = 42.0
            self.recovery_mass_phase_comp[0, 'Liq', 'H2O'].value = 0.5
'''

FAKE_PROPERTY = '''
    class NaClParameterBlock:
        def __init__(self, *args, **kwargs):
            pass

        def set_default_scaling(self, name, factor, index=None):
            import pyomo.environ as _ev
            _ev.EVENTS.append(('default_scaling', name, factor, index))


        def build_state_block(self, *args, **kwargs):
            import pyomo.environ as _pe
            return _pe._State()
'''

PYOMO_BLOCK_EXTENSION = '''


class _ControlVolume:
    def __init__(self):
        self.properties_in = [_State()]
        self.properties_out = [_State()]
        self.work = _Var('work')


class _FeedSide:
    def __init__(self):
        self.properties_in = [_State()]
        self.properties = {0.0: _State()}
        self.properties[0, 0] = _State()
        self.properties_out = [_State()]
        self.cp_modulus = _Var('cp_modulus')
        del self.properties[0.0]


class _Chemical:
    def __init__(self):
        self.outlet_state = _State()


class _Block:
    def __init__(self, *args, **kwargs):
        self.inlet = _Port()
        self.outlet = _Port()
        self.permeate = _Port()
        self.control_volume = _ControlVolume()
        self.feed_side = _FeedSide()
        self.chemical = _Chemical()
        self.mixed_permeate = {0.0: _State()}
        self.properties = {0.0: _State()}
        self.area = _Var('area')
        self.A_comp = _Var('A_comp')
        self.B_comp = _Var('B_comp')
        self.deltaP = _Var('deltaP')
        self.efficiency_pump = _Var('efficiency_pump')
        self.recovery_mass_phase_comp = _Indexed()

    def del_component(self, component):
        import pyomo.environ as _ev
        _ev.EVENTS.append(('del_component', component))

    def component_data_objects(self, ctype, active=True):
        return []
'''
