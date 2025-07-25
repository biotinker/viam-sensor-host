# Module sensor-host 

This module hosts sensor readings on a web server, providing JSON data via HTTP. It periodically collects readings from configured sensors on the same robot and serves them as JSON files accessible through a simple HTTP server.

## Model biotinker:sensor-host:sensor-host

The sensor-host component takes a list of sensors and exposes their readings via an HTTP server on a specified port. Each sensor's readings are stored in individual JSON files that are updated at regular intervals.

### Configuration
The following attribute template can be used to configure this model:

```json
{
  "sensors": ["sensor1", "sensor2"],
  "port": 8080,
  "refresh": 5.0
}
```

#### Attributes

The following attributes are available for this model:

| Name      | Type     | Inclusion | Description                                    |
|-----------|----------|-----------|------------------------------------------------|
| `sensors` | []string | Required  | List of sensor component names to monitor     |
| `port`    | int      | Required  | HTTP port to serve JSON files (1-65535)       |
| `refresh` | float    | Optional  | Refresh interval in seconds (default: 5.0)    |

#### Example Configuration

```json
{
  "sensors": ["my-sensor", "temperature-sensor", "humidity-sensor"],
  "port": 8080,
  "refresh": 3.0
}
```

### Usage

Once configured, the sensor host will:

1. Create temporary directories for each sensor in `/dev/shm/`
2. Start an HTTP server on the specified port
3. Periodically call `get_readings()` on each sensor
4. Save readings to JSON files at `/{sensor_name}/current.json`

You can access sensor readings via HTTP:
- `http://robot-address:8080/sensor1/current.json`
- `http://robot-address:8080/sensor2/current.json`

### DoCommand

The sensor host supports the following DoCommand operations:

#### Status Command

Get the current status of the sensor host:

```json
{
  "status": true
}
```

Response:
```json
{
  "running": true,
  "port": 8080,
  "sensors": ["sensor1", "sensor2"],
  "refresh_interval": 5.0,
  "temp_dir": "/dev/shm/sensor_host_xxx"
}
```

#### Refresh Command

Force an immediate refresh of all sensor readings:

```json
{
  "refresh_now": true
}
```

Response:
```json
{
  "message": "Sensor readings refreshed"
}
```
