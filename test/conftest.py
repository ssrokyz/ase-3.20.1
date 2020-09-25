from pathlib import Path
from subprocess import Popen, PIPE, check_output
import zlib

import pytest
import numpy as np

import ase
from ase.utils import workdir
from ase.test.factories import (CalculatorInputs,
                                factory_classes,
                                NoSuchCalculator,
                                get_factories,
                                make_factory_fixture)
from ase.dependencies import all_dependencies

helpful_message = """\
 * Use --calculators option to select calculators.

 * See "ase test --help-calculators" on how to configure calculators.

 * This listing only includes external calculators known by the test
   system.  Others are "configured" by setting an environment variable
   like "ASE_xxx_COMMAND" in order to allow tests to run.  Please see
   the documentation of that individual calculator.
"""


def pytest_report_header(config, startdir):
    yield from library_header()
    yield ''
    yield from calculators_header(config)


def library_header():
    yield ''
    yield 'Libraries'
    yield '========='
    yield ''
    for name, path in all_dependencies():
        yield '{:24} {}'.format(name, path)


def calculators_header(config):
    try:
        factories = get_factories(config)
    except NoSuchCalculator as err:
        pytest.exit(f'No such calculator: {err}')

    configpaths = factories.executable_config_paths
    module = factories.datafiles_module

    yield ''
    yield 'Calculators'
    yield '==========='

    if not configpaths:
        configtext = 'No configuration file specified'
    else:
        configtext = ', '.join(str(path) for path in configpaths)
    yield f'Config: {configtext}'

    if module is None:
        datafiles_text = 'ase-datafiles package not installed'
    else:
        datafiles_text = str(Path(module.__file__).parent)

    yield f'Datafiles: {datafiles_text}'
    yield ''

    for name in sorted(factory_classes):
        if name in factories.builtin_calculators:
            # Not interesting to test presence of builtin calculators.
            continue

        factory = factories.factories.get(name)

        if factory is None:
            configinfo = 'not installed'
        else:
            # Some really ugly hacks here:
            if hasattr(factory, 'importname'):
                import importlib
                module = importlib.import_module(factory.importname)
                configinfo = str(module.__path__[0])  # type: ignore
            else:
                configtokens = []
                for varname, variable in vars(factory).items():
                    configtokens.append(f'{varname}={variable}')
                configinfo = ', '.join(configtokens)

        run = '[x]' if factories.enabled(name) else '[ ]'
        line = f'  {run} {name:10} {configinfo}'
        yield line

    yield ''
    yield helpful_message
    yield ''

    # (Where should we do this check?)
    for name in factories.requested_calculators:
        if not factories.is_adhoc(name) and not factories.installed(name):
            pytest.exit(f'Calculator "{name}" is not installed.  '
                        'Please run "ase test --help-calculators" on how '
                        'to install calculators')


@pytest.fixture(scope='session')
def require_vasp(factories):
    factories.require('vasp')


@pytest.fixture(scope='session', autouse=True)
def monkeypatch_disabled_calculators(request, factories):
    # XXX Replace with another mechanism.
    factories.monkeypatch_disabled_calculators()


@pytest.fixture(autouse=True)
def use_tmp_workdir(tmp_path):
    # Pytest can on some systems provide a Path from pathlib2.  Normalize:
    path = Path(str(tmp_path))
    with workdir(path, mkdir=True):
        yield tmp_path
    # We print the path so user can see where test failed, if it failed.
    print(f'Testpath: {path}')


@pytest.fixture(scope='session')
def tkinter():
    import tkinter
    try:
        tkinter.Tk()
    except tkinter.TclError as err:
        pytest.skip('no tkinter: {}'.format(err))


@pytest.fixture(scope='session')
def plt(tkinter):
    # XXX Probably we can get rid of tkinter requirement.
    matplotlib = pytest.importorskip('matplotlib')
    matplotlib.use('Agg')

    import matplotlib.pyplot as plt
    return plt


@pytest.fixture
def figure(plt):
    fig = plt.figure()
    yield fig
    plt.close(fig)


@pytest.fixture(scope='session')
def psycopg2():
    return pytest.importorskip('psycopg2')


@pytest.fixture(scope='session')
def factories(pytestconfig):
    return get_factories(pytestconfig)


# XXX Maybe we should not have individual factory fixtures, we could use
# the decorator @pytest.mark.calculator(name) instead.
abinit_factory = make_factory_fixture('abinit')
cp2k_factory = make_factory_fixture('cp2k')
dftb_factory = make_factory_fixture('dftb')
espresso_factory = make_factory_fixture('espresso')
gpaw_factory = make_factory_fixture('gpaw')
octopus_factory = make_factory_fixture('octopus')
siesta_factory = make_factory_fixture('siesta')


@pytest.fixture
def factory(request, factories):
    name, kwargs = request.param
    if not factories.installed(name):
        pytest.skip(f'Not installed: {name}')
    factory = factories[name]
    return CalculatorInputs(factory, kwargs)


def pytest_generate_tests(metafunc):
    from ase.test.factories import parametrize_calculator_tests
    parametrize_calculator_tests(metafunc)

    if 'seed' in metafunc.fixturenames:
        seeds = metafunc.config.getoption('seed')
        if len(seeds) == 0:
            seeds = [0, 1]
        else:
            seeds = list(map(int, seeds))
        metafunc.parametrize('seed', seeds)


class CLI:
    def __init__(self, calculators):
        self.calculators = calculators

    def ase(self, *args):
        proc = Popen(['ase', '-T'] + list(args),
                     stdout=PIPE, stdin=PIPE)
        stdout, _ = proc.communicate(b'')
        status = proc.wait()
        assert status == 0
        return stdout.decode('utf-8')

    def shell(self, command, calculator_name=None):
        if calculator_name is not None:
            self.calculators.require(calculator_name)

        actual_command = ' '.join(command.split('\n')).strip()
        output = check_output(actual_command, shell=True)
        return output.decode()


@pytest.fixture(scope='session')
def cli(factories):
    return CLI(factories)


@pytest.fixture(scope='session')
def datadir():
    test_basedir = Path(__file__).parent
    return test_basedir / 'testdata'


@pytest.fixture
def pt_eam_potential_file(datadir):
    # EAM potential for Pt from LAMMPS, also used with eam calculator.
    # (Where should this fixture really live?)
    return datadir / 'eam_Pt_u3.dat'


@pytest.fixture(scope='session')
def asap3():
    return pytest.importorskip('asap3')


@pytest.fixture(autouse=True)
def arbitrarily_seed_rng(request):
    # We want tests to not use global stuff such as np.random.seed().
    # But they do.
    #
    # So in lieu of (yet) fixing it, we reseed and unseed the random
    # state for every test.  That makes each test deterministic if it
    # uses random numbers without seeding, but also repairs the damage
    # done to global state if it did seed.
    #
    # In order not to generate all the same random numbers in every test,
    # we seed according to a kind of hash:
    ase_path = ase.__path__[0]
    abspath = Path(request.module.__file__)
    relpath = abspath.relative_to(ase_path)
    module_identifier = relpath.as_posix()  # Same on all platforms
    function_name = request.function.__name__
    hashable_string = f'{module_identifier}:{function_name}'
    # We use zlib.adler32() rather than hash() because Python randomizes
    # the string hashing at startup for security reasons.
    seed = zlib.adler32(hashable_string.encode('ascii')) % 12345
    # (We should really use the full qualified name of the test method.)
    state = np.random.get_state()
    np.random.seed(seed)
    yield
    np.random.set_state(state)


def pytest_addoption(parser):
    parser.addoption('--calculators', metavar='NAMES', default='',
                     help='comma-separated list of calculators to test or '
                     '"auto" for all configured calculators')
    parser.addoption('--seed', action='append', default=[],
                     help='add a seed for tests where random number generators'
                          ' are involved. This option can be applied more'
                          ' than once.')
