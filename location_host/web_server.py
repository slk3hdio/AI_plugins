#!/usr/bin/env python3
"""
位置信息接收服务器
接收来自Android应用的位置上报
"""

from datetime import datetime
import csv
import glob
import os
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Path, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from fastapi_mcp import FastApiMCP as MCP

from typing import Annotated

app = FastAPI(title="位置接收服务器")
logger = logging.getLogger("location_server")

# 初始化 MCP
mcp = MCP(app)
# 存储位置数据的目录
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
FIELDNAMES = [
    "user_id",
    "latitude",
    "longitude",
    "accuracy",
    "provider",
    "timestamp",
    "address",
    "country",
    "province",
    "city",
    "district",
    "street",
    "adcode",
    "town",
    "location_describe",
    "received_at",
    "ip",
]
USER_MAPPING = {
    "2838759290": "default_user",
    "astrbot": "default_user"
}


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def current_data_file():
    return os.path.join(DATA_DIR, f"locations_{datetime.now().strftime('%Y-%m-%d')}.csv")


def parse_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None
    
class LocationInput(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    provider: Optional[str] = "unknown"
    timestamp: Optional[str] = None
    address: Optional[str] = None
    country: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    street: Optional[str] = None
    adcode: Optional[str] = None
    town: Optional[str] = None
    location_describe: Optional[str] = None


def load_locations_in_range(start_date: str|None=None, end_date: str|None=None, user_id: str|None=None):
    """加载指定日期范围内的位置数据"""
    ensure_data_dir()
    locations = []
    start = datetime.fromisoformat(start_date) if start_date else datetime.min
    end = datetime.fromisoformat(end_date) if end_date else datetime.max

    for file_path in sorted(glob.glob(os.path.join(DATA_DIR, "locations_*.csv"))):
        # 提取文件名中的日期
        file_date_str = os.path.basename(file_path).replace("locations_", "").replace(".csv", "")
        try:
            file_date = datetime.strptime(file_date_str, "%Y-%m-%d")
            if start.date() <= file_date.date() <= end.date():
                with open(file_path, "r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if user_id and row.get("user_id") != user_id:
                            continue
                        locations.append({
                            "user_id": row.get("user_id"),
                            "latitude": parse_float(row.get("latitude")),
                            "longitude": parse_float(row.get("longitude")),
                            "accuracy": parse_float(row.get("accuracy")),
                            "provider": row.get("provider"),
                            "timestamp": row.get("timestamp"),
                            "address": row.get("address"),
                            "country": row.get("country"),
                            "province": row.get("province"),
                            "city": row.get("city"),
                            "district": row.get("district"),
                            "street": row.get("street"),
                            "adcode": row.get("adcode"),
                            "town": row.get("town"),
                            "location_describe": row.get("location_describe"),
                            "received_at": row.get("received_at"),
                            "ip": row.get("ip"),
                        })
        except ValueError:
            continue  # 跳过无法解析的文件

    # 按 received_at 排序
    locations.sort(key=lambda x: x["received_at"] if x["received_at"] else "")
    return locations


def save_location(location_record):
    """追加新的位置记录到当天CSV文件"""
    ensure_data_dir()
    file_path = current_data_file()
    file_exists = os.path.exists(file_path)
    with open(file_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow(location_record)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(x) for x in err.get("loc", []))
        errors.append({
            "location": loc,
            "message": err.get("msg", ""),
            "type": err.get("type", ""),
        })
    logger.error(f"请求参数验证失败: {errors}")
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": "请求参数验证失败",
            "details": errors,
        },
    )


@app.post("/api/location")
def receive_location(data: LocationInput, request: Request):
    """接收位置信息"""
    location_record = {
        "user_id": "default_user",  # 目前只支持单用户，可以扩展为多用户
        "latitude": data.latitude,
        "longitude": data.longitude,
        "accuracy": data.accuracy,
        "provider": data.provider,
        "timestamp": data.timestamp,
        "address": data.address,
        "country": data.country,
        "province": data.province,
        "city": data.city,
        "district": data.district,
        "street": data.street,
        "adcode": data.adcode,
        "town": data.town,
        "location_describe": data.location_describe,
        "received_at": datetime.now().isoformat(),
        "ip": request.client.host if request.client else None,
    }

    save_location(location_record)

    logger.info(
        f"收到位置: "
        f"({location_record['latitude']:.5f}, {location_record['longitude']:.5f}, {location_record['location_describe']}) "
        f"来自 {location_record['ip']}"
    )

    return {
        "success": True,
        "message": "位置已接收"
    }


@app.get("/api/locations/latest", operation_id="get_latest_location", summary="get the user's latest location record")
def get_latest_location(user_id: Annotated[Optional[str], Query(description="user id, leave empty for any user")] = None):
    """获取最新的位置记录"""
    if user_id and user_id in USER_MAPPING:
        user_id = USER_MAPPING[user_id]
    locations = load_locations_in_range(user_id=user_id)
    if not locations:
        raise HTTPException(status_code=404, detail="没有位置记录")
    # if user_id:
    #     filtered = [loc for loc in locations if loc.get("user_id") == user_id]
    #     if filtered:
    #         return filtered[-1]
    return locations[-1]


@app.get("/api/trajectory", operation_id="get_trajectory", summary="get the user's trajectory in a date range")
def get_trajectory(user_id: Annotated[Optional[str], Query(description="user id, leave empty for any user")] = None, start_date: Annotated[Optional[str], Query(description="start date, format: YYYY-MM-DD, leave empty for today")]=None, end_date: Annotated[Optional[str], Query(description="end date, format: YYYY-MM-DD, leave empty for start date")]=None):
    """获取指定日期内的行动轨迹，只有当location_describe发生变化时才记录为一个节点"""
    if user_id and user_id in USER_MAPPING:
        user_id = USER_MAPPING[user_id]
    if not start_date:
        today = datetime.now().date()
        start_date = today.isoformat()
    if not end_date:
        end_date = start_date
    
    try:
        # 验证日期格式
        datetime.fromisoformat(start_date)
        datetime.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式无效，请使用ISO格式，如2023-01-01")
    
    locations = load_locations_in_range(user_id=user_id, start_date=start_date, end_date=end_date)
    if not locations:
        return {"count": 0, "trajectory": []}
    
    trajectory = []
    previous_describe = None
    for loc in locations:
        current_describe = loc.get("location_describe")
        if not current_describe:
            continue  # 如果没有描述信息，跳过这个记录

        if current_describe != previous_describe:
            trajectory.append({'address': loc.get("address"), 'describe': current_describe, 'timestamp': loc.get("timestamp")})
            previous_describe = current_describe
    if not trajectory:
        return {"count": 0, "trajectory": []}
    return {
        "count": len(trajectory),
        "trajectory": trajectory,
    }


@app.get("/", response_class=HTMLResponse)
def index():
    """首页 - 简单的状态页面"""
    locations = load_locations_in_range()
    return f"""
    <html>
    <head>
        <title>位置接收服务器</title>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }}
            h1 {{ color: #333; }}
            .info {{ background: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            .endpoint {{ background: #e8f5e9; padding: 10px; margin: 10px 0; border-left: 4px solid #4caf50; }}
            code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-family: monospace; }}
        </style>
    </head>
    <body>
        <h1>📍 位置接收服务器</h1>
        <div class="info">
            <p><strong>状态:</strong> 运行中</p>
            <p><strong>已接收记录:</strong> {len(locations)}</p>
        </div>
    </body>
    </html>
    """
mcp = MCP(app,include_operations=['get_latest_location', 'get_trajectory'])
mcp.mount_http() 
