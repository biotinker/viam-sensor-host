from typing import (Any, ClassVar, Dict, Final, List, Mapping, Optional,
                    Sequence, Tuple)
import asyncio
import json
import os
import tempfile
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import functools

from typing_extensions import Self
from viam.components.generic import *
from viam.components.sensor import Sensor
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import Geometry, ResourceName
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.utils import ValueTypes


class SensorHost(Generic, EasyResource):
    # To enable debug-level logging, either run viam-server with the --debug option,
    # or configure your resource/machine to display debug logs.
    MODEL: ClassVar[Model] = Model(
        ModelFamily("biotinker", "sensor-host"), "sensor-host"
    )
    
    def __init__(self, name: str):
        super().__init__(name)
        self.sensors: List[Sensor] = []
        self.port: int = 8080
        self.refresh_interval: float = 5.0
        self.server: Optional[HTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.refresh_task: Optional[asyncio.Task] = None
        self.temp_dir: Optional[str] = None
        self.running = False

    @classmethod
    def new(
        cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> Self:
        """This method creates a new instance of this Generic component.
        The default implementation sets the name from the `config` parameter and then calls `reconfigure`.

        Args:
            config (ComponentConfig): The configuration for this resource
            dependencies (Mapping[ResourceName, ResourceBase]): The dependencies (both required and optional)

        Returns:
            Self: The resource
        """
        return super().new(config, dependencies)

    @classmethod
    def validate_config(
        cls, config: ComponentConfig
    ) -> Tuple[Sequence[str], Sequence[str]]:
        """This method allows you to validate the configuration object received from the machine,
        as well as to return any required dependencies or optional dependencies based on that `config`.

        Args:
            config (ComponentConfig): The configuration for this resource

        Returns:
            Tuple[Sequence[str], Sequence[str]]: A tuple where the
                first element is a list of required dependencies and the
                second element is a list of optional dependencies
        """
        # Validate required configuration
        if "sensors" not in config.attributes.fields:
            raise ValueError("'sensors' attribute is required")
        
        sensor_names = config.attributes.fields["sensors"].list_value
        if len(sensor_names.values) == 0:
            raise ValueError("At least one sensor must be specified")
        
        if "port" not in config.attributes.fields:
            raise ValueError("'port' attribute is required")
        
        port = config.attributes.fields["port"].number_value
        if port <= 0 or port > 65535:
            raise ValueError("Port must be between 1 and 65535")
        
        # Extract sensor names for dependencies
        required_deps = []
        for sensor_value in sensor_names.values:
            sensor_name = sensor_value.string_value
            required_deps.append(sensor_name)
        
        return required_deps, []

    def reconfigure(
        self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ):
        """This method allows you to dynamically update your service when it receives a new `config` object.

        Args:
            config (ComponentConfig): The new configuration
            dependencies (Mapping[ResourceName, ResourceBase]): Any dependencies (both required and optional)
        """
        # Stop existing server if running
        self._stop_server()
        
        # Extract configuration
        sensor_names = config.attributes.fields["sensors"].list_value
        self.port = int(config.attributes.fields["port"].number_value)
        
        # Optional refresh interval (default 5 seconds)
        if "refresh" in config.attributes.fields:
            self.refresh_interval = config.attributes.fields["refresh"].number_value
            if self.refresh_interval <= 0:
                self.refresh_interval = 5.0
        else:
            self.refresh_interval = 5.0
        
        # Setup sensors from dependencies
        self.sensors = []
        for sensor_value in sensor_names.values:
            sensor_name = sensor_value.string_value
            sensor_resource_name = Sensor.get_resource_name(sensor_name)
            if sensor_resource_name in dependencies:
                self.sensors.append(dependencies[sensor_resource_name])
            else:
                self.logger.warning(f"Sensor '{sensor_name}' not found in dependencies")
        
        # Setup temporary directory for JSON files
        self._setup_temp_directory()
        
        # Start web server and refresh task
        self._start_server()
        self._start_refresh_task()
        
        self.running = True
        self.logger.info(f"SensorHost configured with {len(self.sensors)} sensors on port {self.port}")
        
        return super().reconfigure(config, dependencies)

    async def do_command(
        self,
        command: Mapping[str, ValueTypes],
        *,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Mapping[str, ValueTypes]:
        """Handle custom commands for the sensor host"""
        if "status" in command:
            return {
                "running": self.running,
                "port": self.port,
                "sensors": [sensor.name for sensor in self.sensors],
                "refresh_interval": self.refresh_interval,
                "temp_dir": self.temp_dir or ""
            }
        elif "refresh_now" in command:
            if self.running:
                await self._update_all_sensor_readings()
                return {"message": "Sensor readings refreshed"}
            else:
                return {"error": "SensorHost not running"}
        else:
            return {"error": f"Unknown command: {list(command.keys())}"}

    async def get_geometries(
        self, *, extra: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> List[Geometry]:
        return []
    
    def _setup_temp_directory(self):
        """Setup temporary directory structure for JSON files"""
        if self.temp_dir:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        
        self.temp_dir = tempfile.mkdtemp(dir="/dev/shm", prefix="sensor_host_")
        
        # Create subdirectory for each sensor
        for sensor in self.sensors:
            sensor_dir = os.path.join(self.temp_dir, sensor.name)
            os.makedirs(sensor_dir, exist_ok=True)
            
        self.logger.info(f"Created temp directory: {self.temp_dir}")
    
    def _start_server(self):
        """Start HTTP server to serve JSON files"""
        if self.server:
            return
            
        try:
            handler = functools.partial(SimpleHTTPRequestHandler, directory=self.temp_dir)
            self.server = HTTPServer(('0.0.0.0', self.port), handler)
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            self.logger.info(f"HTTP server started on port {self.port}")
        except Exception as e:
            self.logger.error(f"Failed to start HTTP server: {e}")
            raise
    
    def _stop_server(self):
        """Stop HTTP server and cleanup resources"""
        if self.refresh_task and not self.refresh_task.done():
            self.refresh_task.cancel()
            self.refresh_task = None
        
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
            
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=1.0)
            self.server_thread = None
            
        if self.temp_dir and os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir = None
            
        self.running = False
        self.logger.info("HTTP server stopped and resources cleaned up")
    
    def _start_refresh_task(self):
        """Start async task to periodically refresh sensor readings"""
        if self.refresh_task and not self.refresh_task.done():
            self.refresh_task.cancel()
            
        loop = asyncio.get_event_loop()
        self.refresh_task = loop.create_task(self._refresh_readings_loop())
        self.logger.info(f"Started refresh task with {self.refresh_interval}s interval")
    
    async def _refresh_readings_loop(self):
        """Continuously refresh sensor readings and save to JSON files"""
        while self.running:
            try:
                await asyncio.sleep(self.refresh_interval)
                await self._update_all_sensor_readings()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in refresh loop: {e}")
    
    async def _update_all_sensor_readings(self):
        """Update readings for all sensors"""
        for sensor in self.sensors:
            try:
                await self._update_sensor_reading(sensor)
            except Exception as e:
                self.logger.error(f"Failed to update readings for sensor {sensor.name}: {e}")
    
    async def _update_sensor_reading(self, sensor: Sensor):
        """Update readings for a single sensor"""
        try:
            readings = await sensor.get_readings()
            sensor_dir = os.path.join(self.temp_dir, sensor.name)
            
            # Write to temporary file first, then rename for atomic update
            temp_file = os.path.join(sensor_dir, "next.json")
            current_file = os.path.join(sensor_dir, "current.json")
            
            with open(temp_file, 'w') as f:
                json.dump(readings, f, indent=2, default=str)
            
            # Atomic rename for consistent reads
            os.replace(temp_file, current_file)
            
        except Exception as e:
            self.logger.error(f"Failed to get readings from sensor {sensor.name}: {e}")
            raise
    
    def __del__(self):
        """Cleanup on object destruction"""
        if self.running:
            self._stop_server()

