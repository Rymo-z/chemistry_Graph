"""PPED_data.zip 并行分片断点续传下载器。

Zenodo 单连接 ~590KB/s 且每几分钟断一次，用多连接分片拉取：
- 文件按字节切成 N 段，每段独立线程 + 独立 Range 请求下载到 .partNN 文件；
- 每段崩溃后从已写入长度断点续传（resume），线程内自动重试；
- 全部完成后按序拼接为 PPED_data.zip，校验总大小后清理分片。

用法：
    python -m _007_fine_tune.download_pped          # 默认 8 段
    python -m _007_fine_tune.download_pped --segments 12
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import requests

URL = "https://zenodo.org/records/6551758/files/PPED_data.zip?download=1"
OUT = Path(__file__).parent / "datasets" / "PPED_data.zip"
CHUNK = 1 << 20  # 1MB 读块


def get_total_size(url: str) -> int:
    """用 Range: bytes=0-0 探出总大小（HEAD 对 Zenodo 重定向不靠谱）。

    与 _fetch_range 同样带重试：代理/服务器会随机断流（SSL EOF），单次失败
    不应让整个下载器崩溃退出。
    """
    for attempt in range(8):
        try:
            r = requests.get(url, headers={"Range": "bytes=0-0"}, timeout=30)
            r.raise_for_status()
            cr = r.headers.get("Content-Range", "")
            if "/" in cr:
                return int(cr.split("/")[-1])
            return len(r.content)
        except requests.RequestException:
            time.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"无法获取 {url} 总大小，重试耗尽")


def _fetch_range(url: str, start: int, end: int) -> requests.Response:
    """带重试的 Range 请求（503/429/连接断开 → 退避重试）。"""
    for attempt in range(8):
        try:
            r = requests.get(
                url,
                headers={"Range": f"bytes={start}-{end}"},
                stream=True,
                timeout=(15, 120),
            )
            if r.status_code in (200, 206):
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(2 ** attempt, 30))
                continue
            r.raise_for_status()
        except requests.RequestException:
            time.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"分段 {start}-{end} 重试耗尽")


def download_segment(url: str, seg: int, start: int, end: int,
                     part: Path, progress: dict, lock: threading.Lock) -> None:
    """下载 [start, end] 到 part，支持从已写入长度续传。"""
    pos = part.stat().st_size if part.exists() else 0
    pos = max(start, min(start + pos, end))  # part 里存的是相对偏移
    with part.open("ab") as fp:
        while pos < end:
            try:
                resp = _fetch_range(url, pos, end)
            except RuntimeError:
                raise  # 重试耗尽，主线程捕获后按不完整处理（可续传重跑）
            try:
                for chunk in resp.iter_content(CHUNK):
                    if not chunk:
                        continue
                    fp.write(chunk)
                    pos += len(chunk)
                    with lock:
                        progress["downloaded"] += len(chunk)
            except requests.RequestException:
                # 中途断流（IncompleteRead 等）：关闭连接，回退 while 从 pos 续传
                continue
            finally:
                resp.close()
            if resp.status_code != 206:
                break  # 服务器返回 200 全量，已写满
    with lock:
        progress[f"seg{seg}"] = True


def main() -> None:
    parser = argparse.ArgumentParser(description="PPED 数据集并行续传下载")
    parser.add_argument("--segments", type=int, default=8, help="并发分片数")
    args = parser.parse_args()
    segs = max(1, args.segments)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    total = get_total_size(URL)
    print(f"目标总大小: {total / 1e6:.0f} MB，分 {segs} 段", flush=True)

    # 仅当上次已成功拼出完整 zip 时才清旧分片重下；否则保留分片断点续传。
    # 注意：无条件 unlink 会抹掉中断后的所有进度，绝不可为。
    parts = [OUT.with_name(f"PPED_data.zip.part{i:03d}") for i in range(segs)]
    if OUT.is_file() and OUT.stat().st_size == total:
        for p in parts:
            if p.exists():
                p.unlink()

    span = (total + segs - 1) // segs
    progress: dict = {"downloaded": 0}
    lock = threading.Lock()
    threads: list[threading.Thread] = []

    for i in range(segs):
        start = i * span
        end = min(start + span - 1, total - 1)
        t = threading.Thread(
            target=download_segment,
            args=(URL, i, start, end, parts[i], progress, lock),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # 进度条（线程安全打印）
    t0 = time.time()
    while any(t.is_alive() for t in threads):
        with lock:
            done = progress["downloaded"]
        pct = done / total * 100
        speed = done / max(time.time() - t0, 1) / 1e6
        eta = (total - done) / max(speed, 0.01) / 1e6
        print(f"\r{done/1e6:6.0f}/{total/1e6:.0f} MB  {pct:5.1f}%  "
              f"{speed:5.2f} MB/s  剩余 {eta:.0f}s", end="", flush=True)
        time.sleep(2)
    for t in threads:
        t.join()
    print(flush=True)

    # 校验：按分片累计大小（而非本会话新增字节数）核对，续传场景下
    # progress["downloaded"] 只统计本次运行写入的量，会漏掉历史分片。
    got = sum(p.stat().st_size for p in parts)
    if got < total * 0.999:
        print(f"错误：仅下载 {got/1e6:.0f}/{total/1e6:.0f} MB，请重跑续传", file=sys.stderr)
        sys.exit(1)

    # 按序拼接
    print("拼接分片...", flush=True)
    with OUT.open("wb") as out_fp:
        for p in parts:
            out_fp.write(p.read_bytes())
            p.unlink()
    print(f"完成：{OUT}（{OUT.stat().st_size/1e6:.0f} MB）", flush=True)


if __name__ == "__main__":
    main()
