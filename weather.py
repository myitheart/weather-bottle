from dataclasses import dataclass
import json
from math import isfinite
from urllib.parse import urlencode

from PySide6.QtCore import QObject, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest


@dataclass(frozen=True)
class Location:
    name: str
    latitude: float
    longitude: float

    @classmethod
    def from_data(cls, data, name=None):
        latitude, longitude = float(data["latitude"]), float(data["longitude"])
        label = (name or data.get("name") or "").strip()
        if not label or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Invalid location")
        return cls(label, latitude, longitude)


CONDITIONS = {
    0: ("晴", "sun"), 1: ("大致晴朗", "sun"), 2: ("局部多云", "cumulus"),
    3: ("阴", "overcast"), 45: ("雾", "fog"), 48: ("冻雾", "icefog"),
    51: ("轻微毛毛雨", "drizzle"), 53: ("毛毛雨", "drizzle"), 55: ("密集毛毛雨", "rain"),
    56: ("轻微冻毛毛雨", "coldrain"), 57: ("冻毛毛雨", "coldrain"),
    61: ("小雨", "drizzle"), 63: ("中雨", "rain"), 65: ("大雨", "downpour"),
    66: ("轻微冻雨", "coldrain"), 67: ("强冻雨", "coldrain"),
    71: ("小雪", "snow"), 73: ("中雪", "snow"), 75: ("大雪", "blizzard"),
    77: ("雪粒", "snow"), 80: ("小阵雨", "shower"), 81: ("阵雨", "shower"),
    82: ("强阵雨", "downpour"), 85: ("小阵雪", "snow"), 86: ("强阵雪", "blizzard"),
    95: ("雷阵雨", "thunder"), 96: ("雷暴伴小冰雹", "hail"),
    97: ("强雷暴", "thunder"), 99: ("雷暴伴大冰雹", "hail"),
}


@dataclass(frozen=True)
class CurrentWeather:
    condition: str
    scene: str
    temperature: float
    time: str

    @classmethod
    def from_data(cls, data):
        current = data["current"]
        code = int(current["weather_code"])
        condition, scene = CONDITIONS.get(code, ("未知天气", "overcast"))
        if code in (0, 1) and int(current["is_day"]) == 0:
            scene = "moon"
        temperature = float(current["temperature_2m"])
        if not isfinite(temperature):
            raise ValueError("Invalid temperature")
        return cls(condition, scene, temperature, str(current["time"]))


class WeatherService(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.direct = QNetworkAccessManager(self)
        self.direct.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))

    def locate(self, callback):
        def resolved(data):
            if data.get("success") is not True:
                raise ValueError("IP location unavailable")
            city = data.get("city") or data.get("region")
            if not city:
                raise ValueError("No city")
            return Location.from_data(data, city)

        self.request(
            self.direct, "https://ipwho.is/",
            {"fields": "success,city,region,latitude,longitude"}, resolved, callback,
        )

    def search(self, name, callback):
        def locations(data):
            results = []
            for entry in data.get("results", []):
                parts = dict.fromkeys(entry.get(key) for key in ("name", "admin1", "country"))
                label = " · ".join(part for part in parts if part)
                results.append(Location.from_data(entry, label))
            return results

        self.request(
            self.network, "https://geocoding-api.open-meteo.com/v1/search",
            {"name": name, "count": 8, "language": "zh"}, locations, callback,
        )

    def current(self, location, callback):
        self.request(
            self.network, "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": round(location.latitude, 3),
                "longitude": round(location.longitude, 3),
                "current": "temperature_2m,weather_code,is_day",
                "timezone": "auto",
                "forecast_days": 1,
            },
            CurrentWeather.from_data, callback,
        )

    @staticmethod
    def request(manager, url, params, parse, callback):
        request = QNetworkRequest(QUrl(f"{url}?{urlencode(params)}"))
        request.setTransferTimeout(12000)
        reply = manager.get(request)

        def finished():
            result = None
            try:
                if reply.error() == QNetworkReply.NetworkError.NoError:
                    result = parse(json.loads(bytes(reply.readAll())))
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
            finally:
                reply.deleteLater()
            callback(result)

        reply.finished.connect(finished)
