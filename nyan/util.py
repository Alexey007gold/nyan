import json
import math
import os
import random
from dataclasses import dataclass, asdict, fields
from datetime import datetime
from typing import TypeVar, List, Any, Iterable, Dict, Type

import numpy as np
import pytz
import requests
import torch
from pytz import timezone


def read_jsonl(file_path: str, sample_rate: float = 1.0) -> Iterable[Dict[str, Any]]:
    assert os.path.exists(file_path)
    with open(file_path) as r:
        for line in r:
            if not line:
                continue
            if random.random() > sample_rate:
                continue
            yield json.loads(line)


def write_jsonl(file_path: str, records: List[Dict[str, Any]]) -> None:
    with open(file_path, "w") as w:
        for record in records:
            w.write(json.dumps(record, ensure_ascii=False).strip() + "\n")


def get_current_ts() -> int:
    return int(get_current_datetime().timestamp())

def get_current_datetime():
    return datetime.now(pytz.utc)

def ts_to_dt(timestamp: int, tz: str = None) -> datetime:
    if not tz:
        tz = find_timezone_by_local_offset()
    return datetime.fromtimestamp(timestamp, timezone(tz))

def find_timezone_by_local_offset() -> str:
    local = datetime.now().replace(tzinfo=timezone("UTC"))
    utc = datetime.now(timezone("UTC"))
    offset_minutes = math.ceil((local - utc).seconds / 60)

    for tzName in pytz.all_timezones:
        if offset_minutes == datetime.now(timezone(tzName)).utcoffset().total_seconds()/60:
            return tzName

    return "UTC"



T = TypeVar("T", bound="Serializable")


@dataclass
class Serializable:
    @classmethod
    def fromdict(cls: Type[T], d: Dict[str, Any]) -> T:
        if d is None:
            return None
        keys = {f.name for f in fields(cls)}
        d = {k: v for k, v in d.items() if k in keys}
        return cls(**d)

    def asdict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def deserialize(cls: Type[T], line: str) -> T:
        return cls.fromdict(json.loads(line))

    def serialize(self) -> str:
        return json.dumps(self.asdict(), ensure_ascii=False)


def set_random_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:2"
    os.environ["PL_GLOBAL_SEED"] = str(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)


def gen_batch(records: List[Any], batch_size: int) -> Iterable[List[Any]]:
    batch_start = 0
    while batch_start < len(records):
        batch_end = batch_start + batch_size
        batch = records[batch_start:batch_end]
        batch_start = batch_end
        yield batch

def unique_by(items, key_func):
    seen = set()
    return [item for item in items if not (key := key_func(item)) in seen or seen.add(key)]

def url_content_len(url: str) -> int:
    return requests.head(url, allow_redirects=False).headers.get('content-length', 0)
