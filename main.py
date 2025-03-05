import json
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from typing import Union, Optional, List
import uvicorn
from fastapi import Depends, FastAPI, Query, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from typing_extensions import Annotated
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request


# limiter is used to mitigate DoS attacks
# limiter = Limiter(key_func=get_remote_address, key_style="endpoint", default_limits=["10/minute"])
security = HTTPBasic()
app = FastAPI(dependencies=[Depends(security)])
# app.state.limiter = limiter
# app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# app.add_middleware(SlowAPIMiddleware)

users = {
    "admin": {
        "password": "Password123"
    }
}


@app.on_event("startup")
async def startup():
    app.state.pool = await create_con_pool_to_pg_db()
    app.state.routing_finder = RoutingFinder(app.state.pool)


@app.on_event("shutdown")
async def app_shutdown():
    await app.state.pool.close()


# User Verification Function
def verification(creds: HTTPBasicCredentials = Depends(security)):
    username = creds.username
    password = creds.password
    if username in users and password == users[username]["password"]:
        print("User Validated")
        return True
    else:
        # From FastAPI
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect user or password",
            headers={"WWW-Authenticate": "Basic"},)

# @app.exception_handler(StarletteHTTPException)
# async def http_exception_handler(request, exc):
#     return PlainTextResponse(str(exc.detail), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    for errors in exc.errors():
        e_type, loc, msg, val = errors["type"], errors["loc"], errors["msg"], errors["input"]
        param_type = loc[0]
        param = loc[1]

        # path parameters exceptions have precedence over query parameters
        if param_type == 'path':
            if e_type == 'float_parsing':
                return JSONResponse(
                    status_code=400,
                    content={"message": f'Coordinates are not represented as float numbers, {param} = {val}'},
                )
        elif param_type == 'query':
            if e_type == 'bool_parsing':
                if param == 'autovalidate':
                    return JSONResponse(
                        status_code=400,
                        content={"message": f'query parameter autovalidate is boolean (true / false) '
                                            f'autovalidate= {val} is not a valid value'},)
                else:
                    return JSONResponse(
                        status_code=400,
                        content={"message": f'canals or straits parameters are boolean (true / false), '
                                            f'{param} = {val} is not a valid value'},)


@app.get("/")
async def root():
    return "Welcome to MPathic Backend !"


class MaritimeCoordinate(BaseModel):
    lat: float
    lng: float


class MaritimeRoutingOptions(BaseModel):
    suez: Optional[bool] = True
    panama: Optional[bool] = True
    kiel: Optional[bool] = True
    corinth: Optional[bool] = False
    gibraltar: Optional[bool] = True
    messina: Optional[bool] = True
    singapore: Optional[bool] = True
    dover: Optional[bool] = True
    magellan: Optional[bool] = True
    floridaStrait: Optional[bool] = True
    bosphorus: Optional[bool] = True
    oresund: Optional[bool] = True
    eca: Optional[str] = 'ignore'
    hra: Optional[str] = 'ignore'
    jwc: Optional[str] = 'ignore'
    autovalidate: Optional[bool] = False


class MaritimeRoutingReq(BaseModel):
    id: Optional[str] = None
    src: MaritimeCoordinate = Field(alias='from')
    target: MaritimeCoordinate = Field(alias='to')
    averageVesselSpeedOverGround: Annotated[Optional[float], Query(ge=1.0, le=100.0)] = 15.0
    options: Optional[MaritimeRoutingOptions] = MaritimeRoutingOptions()


class MaritimeCoordinateValidationReqList(BaseModel):
    requests: List[MaritimeCoordinate]


class MaritimeRoutingReqList(BaseModel):
    requests: List[MaritimeRoutingReq]


async def get_vtx_to_vtx_data(src_lon: float, src_lat: float, target_lon: float, target_lat: float):
    return await app.state.routing_finder.get_vtx_to_vtx_data(src_lon, src_lat, target_lon, target_lat)


async def do_node_validation(lon: float, lat: float):
    vd = await app.state.routing_finder.get_node_data(lon, lat)
    area_type_to_name = dict(zip(vd.restricted_areas_type, vd.restricted_areas_name))

    data = {'is_valid': vd.distance == 0,
            'suggestion': [vd.v_lon, vd.v_lat],
            'normalized': [vd.n_lon, vd.n_lat],
            'moved_by': vd.distance,
            'validatedLatlng': {"lat": vd.v_lat, "lng": vd.v_lon},
            'eca': 'ECA' in area_type_to_name,
            'eca_name': area_type_to_name['ECA'] if 'ECA' in area_type_to_name else 'No ECA',
            'hra': 'HRA' in area_type_to_name,
            'hra_name': area_type_to_name['HRA'] if 'HRA' in area_type_to_name else 'No HRA',
            'jwc': 'JWC' in area_type_to_name,
            'jwc_name': area_type_to_name['JWC'] if 'JWC' in area_type_to_name else 'No JWC',
            'timezone_of_validated': vd.timezone_str}
    # json_data = json.dumps(data)
    return data


@app.post("/v1/validate")
# @limiter.limit("5/minute")
async def v1_validate(request: Request, data: MaritimeCoordinateValidationReqList, user_verification=Depends(verification)):
    if user_verification:
        try:
            validations = []
            for req in data.requests:
                validation_data = await do_node_validation(req.lng, req.lat)
                validations.append(validation_data)
            return JSONResponse(status_code=200, content=validations, )

        except psycopg2.Error as e:
            return JSONResponse(status_code=500, content={"message": f'something went wrong in PostgreSQL DB session, '
                                                                     f'error: {e.pgerror}'}, )
        except Exception as e:
            return JSONResponse(status_code=500, content={"message": str(e)}, )


@app.get("/v1/validate/{lon}/{lat}")
# @limiter.limit("5/minute")
async def v1_validate(request: Request, lon: float, lat: float, user_verification=Depends(verification)):
    if user_verification:
        try:
            validation_data = await do_node_validation(lon, lat)
            return JSONResponse(status_code=200, content=validation_data, )

        except psycopg2.Error as e:
            return JSONResponse(status_code=500, content={"message": f'something went wrong in PostgreSQL DB session, '
                                                                     f'error: {e.pgerror}'}, )
        except Exception as e:
            return JSONResponse(status_code=500, content={"message": str(e)}, )


if __name__ == "__main__":
    uvicorn.run(app)
