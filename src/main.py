import asyncio
from viam.module.module import Module
try:
    from models.sensor_host import SensorHost
except ModuleNotFoundError:
    # when running as local module with run.sh
    from .models.sensor_host import SensorHost


if __name__ == '__main__':
    asyncio.run(Module.run_from_registry())
