from bigqmt_autotrader.core import ExecutionDriver
from bigqmt_autotrader.drivers import SimulatedDriver


def test_simulated_driver_satisfies_execution_driver_port():
    assert isinstance(SimulatedDriver(), ExecutionDriver)
