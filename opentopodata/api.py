import logging
import os

from flask import Flask, jsonify, request
from flask_caching import Cache
import polyline

from opentopodata import backend, config


app = Flask(__name__)
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = True

DEFAULT_INTERPOLATION_METHOD = "bilinear"
MEMCACHED_SOCKET = "/tmp/memcached.sock"
LAT_MIN = -90
LAT_MAX = 90
LON_MIN = -180
LON_MAX = 180


# Memcache is used to store the latlon -> filename lookups, which can take a
# while to compute for datasets made up of many files. Memcache needs to be
# disabled for testing as it breaks tests which change the config. It can also
# be disabled if not installed for local devleopment.
if os.environ.get("DISABLE_MEMCACHE"):
    cache = Cache(config={"CACHE_TYPE": "null", "CACHE_NO_NULL_WARNING": True})
else:
    cache = Cache(
        config={
            "CACHE_TYPE": "memcached",
            "CACHE_MEMCACHED_SERVERS": [MEMCACHED_SOCKET],
            "CACHE_DEFAULT_TIMEOUT": 0,
        }
    )
cache.init_app(app)


@cache.cached(key_prefix="_load_config")
def _load_config():
    """Config file as a dict.

    Returns:
        Config dict.
    """
    return config.load_config()


# Supporting CORSs enables browsers to make XHR requests.
@app.after_request
def apply_cors(response):
    if _load_config()["access_control_allow_origin"]:
        response.headers["access-control-allow-origin"] = _load_config()[
            "access_control_allow_origin"
        ]
    return response


class ClientError(ValueError):
    """Invalid input data.

    A 400 error should be raised. The error message should be safe to pass
    back to the client.
    """

    pass


def _validate_interpolation(method):
    """Check the interpolation method is supported.

    Args:
        method: Name of the interpolation method.

    Raises:
        ClientError: Method is not supported.
    """

    if method not in backend.INTERPOLATION_METHODS:
        msg = f"Invalid interpolation method '{method}' not recognized."
        msg += " Valid interpolation methods: "
        msg += ", ".join(backend.INTERPOLATION_METHODS.keys()) + "."
        raise ClientError(msg)
    return method


def _parse_locations(locations, max_n_locations):
    """Parse and validate the locations GET argument.

    The "locations" argument of the query should be "lat,lon" pairs delimited
    by "|" characters, or a string in Google polyline format.


    Args:
        locations: The location query string.
        max_n_locations: The max allowable number of locations, to keep query times reasonable.

    Returns:
        lats: List of latitude floats.
        lons: List of longitude floats.

    Raises:
        ClientError: If too many locations are given, or if the location string can't be parsed.
    """
    if not locations:
        msg = "No locations provided."
        msg += " Add locations in a query string: ?locations=lat1,lon1|lat2,lon2."
        raise ClientError(msg)

    if "," in locations:
        return _parse_latlon_locations(locations, max_n_locations)
    else:
        return _parse_polyline_locations(locations, max_n_locations)


def _parse_polyline_locations(locations, max_n_locations):
    """Parse and validate locations in Google polyline format.

    The "locations" argument of the query should be a string of ascii characters above 63.


    Args:
        locations: The location query string.
        max_n_locations: The max allowable number of locations, to keep query times reasonable.

    Returns:
        lats: List of latitude floats.
        lons: List of longitude floats.

    Raises:
        ClientError: If too many locations are given, or if the location string can't be parsed.
    """

    # The Google maps API prefixes their polylines with 'enc:'.
    if locations and locations.startswith("enc:"):
        locations = locations[4:]

    try:
        latlons = polyline.decode(locations)
    except Exception as e:
        msg = "Unable to parse locations as polyline."
        raise ClientError(msg)

    # Polyline result in in list of (lat, lon) tuples.
    lats = [p[0] for p in latlons]
    lons = [p[1] for p in latlons]

    # Check number.
    n_locations = len(lats)
    if n_locations > max_n_locations:
        msg = f"Too many locations provided ({n_locations}), the limit is {max_n_locations}."
        raise ClientError(msg)

    return lats, lons


def _parse_latlon_locations(locations, max_n_locations):
    """Parse and validate "lat,lon" pairs delimited by "|" characters.


    Args:
        locations: The location query string.
        max_n_locations: The max allowable number of locations, to keep query times reasonable.

    Returns:
        lats: List of latitude floats.
        lons: List of longitude floats.

    Raises:
        ClientError: If too many locations are given, or if the location string can't be parsed.
    """

    # Check number of points.
    locations = locations.strip("|").split("|")
    n_locations = len(locations)
    if n_locations > max_n_locations:
        msg = f"Too many locations provided ({n_locations}), the limit is {max_n_locations}."
        raise ClientError(msg)

    # Parse each location.
    lats = []
    lons = []
    for i, loc in enumerate(locations):
        if "," not in loc:
            msg = f"Unable to parse location '{loc}' in position {i+1}."
            msg += " Add locations like lat1,lon1|lat2,lon2."
            raise ClientError(msg)

        # Separate lat & lon.
        parts = loc.split(",", 1)
        lat = parts[0]
        lon = parts[1]

        # Cast to numeric.
        try:
            lat = float(lat)
            lon = float(lon)
        except ValueError:
            msg = f"Unable to parse location '{loc}' in position {i+1}."
            raise ClientError(msg)

        # Check bounds.
        if not (LAT_MIN <= lat <= LAT_MAX):
            msg = f"Unable to parse location '{loc}' in position {i+1}."
            msg += f" Latitude must be between {LAT_MIN} and {LAT_MAX}."
            msg += " Provide locations in lat,lon order."
            raise ClientError(msg)
        if not (LON_MIN <= lon <= LON_MAX):
            msg = f"Unable to parse location '{loc}' in position {i+1}."
            msg += f" Longitude must be between {LON_MIN} and {LON_MAX}."
            raise ClientError(msg)

        lats.append(lat)
        lons.append(lon)

    return lats, lons


@cache.cached(key_prefix="_load_datasets")
def _load_datasets():
    """Load datasets defined in config

    Returns:
        Dict of {dataset_name: config.Dataset object} items.
    """
    return config.load_datasets()


def _get_dataset(name):
    """Retrieve a dataset with error handling.

    Args:
        name: Dataset name string (as used in request url and config file).

    Returns:
        config.Dataset object.

    Raises:
        ClientError: If the name isn't defined in the config.
    """
    datasets = _load_datasets()
    if name not in datasets:
        raise ClientError(f"Dataset '{name}' not in config.")
    return datasets[name]


@app.route("/")
def health_check(methods=["GET"]):
    return jsonify({"ok":True}), 200


@app.route("/v1/")
def get_help_message(methods=["GET", "OPTIONS", "HEAD"]):
    msg = "No dataset name provided."
    msg += " Try a url like '/v1/test-dataset?locations=-10,120' to get started,"
    msg += " and see https://www.opentopodata.org for full documentation."
    return jsonify({"status": "INVALID_REQUEST", "error": msg}), 404


@app.route("/v1/<dataset_name>", methods=["GET", "OPTIONS", "HEAD"])
def get_elevation(dataset_name):
    """Calculate the elevavation for the given locations.

    Args:
        dataset_name: String matching a dataset in the config file.

    Returns:
        Response.
    """

    try:
        # Parse inputs.
        interpolation = request.args.get("interpolation", DEFAULT_INTERPOLATION_METHOD)
        interpolation = _validate_interpolation(interpolation)
        locations = request.args.get("locations")
        lats, lons = _parse_locations(
            locations, _load_config()["max_locations_per_request"]
        )

        # Get the z values.
        dataset = _get_dataset(dataset_name)
        elevations = backend.get_elevation(lats, lons, dataset, interpolation)

        # Build response.
        results = []
        for z, lat, lon in zip(elevations, lats, lons):
            results.append({"elevation": z, "location": {"lat": lat, "lng": lon}})
        data = {"status": "OK", "results": results}
        return jsonify(data)

    except (ClientError, backend.InputError) as e:
        return jsonify({"status": "INVALID_REQUEST", "error": str(e)}), 400
    except config.ConfigError as e:
        return jsonify({"status": "SERVER_ERROR", "error": str(e)}), 500
    except Exception as e:
        if app.debug:
            raise e
        app.logger.error(e)
        msg = "Server error, please retry request."
        return jsonify({"status": "SERVER_ERROR", "error": msg}), 500
