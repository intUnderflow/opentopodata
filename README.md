# Open Topo Data


__Documentation__: [www.opentopodata.org](https://www.opentopodata.org).

Open Topo Data is a REST API server for your elevation data. You can host your own, or use the free public API.




## Host your own


```bash
git clone github.com/ajnisbet/opentopodata
cd opentopodata
make build
make run
curl http://localhost:8000/v1/test?locations=56.35,123.90
```

```json
{
    "results": [{
        "elevation": 815.0,
        "location": {
            "lat": 56.0,
            "lng": 123.0
        }
    }],
    "status": "OK"
}
```


See the [server docs](docs/server.md) for more about configuration and adding datasets.


## Public API

I'm hosting a public API at [api.opentopodata.org](https://api.opentopodata.org/v1/test) with a number of different datasets. See the [public API docs](docs/index.md#public-api) for more details.

