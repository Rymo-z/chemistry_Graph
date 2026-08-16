"""数据采集 CLI 入口。

用法示例：
    # 全量抓取法规（带断点续爬，可随时中断后重跑）
    python -m _001_clawler.run_crawler regulation

    # 只抓 5 条，验证链路
    python -m _001_clawler.run_crawler regulation --limit 5

    # 忽略断点强制重抓（会覆盖原始文件）
    python -m _001_clawler.run_crawler regulation --force

    # 自定义间隔（秒，越大越礼貌）与请求数安全阀
    python -m _001_clawler.run_crawler regulation --delay 2 --max-requests 50

    # 抓 gov.cn 政府网法律/行政法规全文（白名单）
    python -m _001_clawler.run_crawler gov --limit 2          # 先小规模验证链路
    python -m _001_clawler.run_crawler gov                    # 白名单全量（断点续爬）
    python -m _001_clawler.run_crawler gov --force            # 忽略断点强制重抓

    # 抓应急管理部「特别重大事故调查报告」（事故案例，P1；来源为官方公开政务信息）
    python -m _001_clawler.run_crawler accident --limit 5     # 先抓 5 份验证链路
    python -m _001_clawler.run_crawler accident               # 全量（~100 份，断点续爬）
    python -m _001_clawler.run_crawler accident --no-pdf      # 仅元数据+PDF链接，不下载 PDF
"""
from __future__ import annotations

import argparse
import sys

from _001_clawler.accident_crawler import AccidentCrawler
from _001_clawler.gov_crawler import GovCrawler
from _001_clawler.regulation_crawler import RegulationCrawler
from common.logger import get_logger

logger = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="化工安全生产合规智能体 · 数据采集")
    sub = parser.add_subparsers(dest="command", required=True)

    reg = sub.add_parser("regulation", help="抓取应急管理部官网规范性文件")
    reg.add_argument("--limit", type=int, default=0, help="最多抓取条数（0=不限）")
    reg.add_argument("--max-pages", type=int, default=0, help="最多列表页数（0=全部）")
    reg.add_argument("--force", action="store_true", help="忽略断点，强制重抓")
    reg.add_argument("--delay", type=float, default=1.5, help="请求间隔下限（秒）")
    reg.add_argument("--max-requests", type=int, default=0, help="本次运行请求数安全阀（0=不限）")

    gov = sub.add_parser("gov", help="抓取 gov.cn 政府网化工安全相关法律/行政法规全文（白名单）")
    gov.add_argument("--limit", type=int, default=0, help="最多抓取条数（0=全部）")
    gov.add_argument("--force", action="store_true", help="忽略断点，强制重抓")
    gov.add_argument("--delay", type=float, default=2.0, help="请求间隔下限（秒）")
    gov.add_argument("--max-requests", type=int, default=0, help="本次运行请求数安全阀（0=不限）")

    acc = sub.add_parser("accident", help="抓取应急管理部特别重大事故调查报告（PDF 全文）")
    acc.add_argument("--limit", type=int, default=0, help="最多抓取条数（0=全部）")
    acc.add_argument("--force", action="store_true", help="忽略断点，强制重抓")
    acc.add_argument("--delay", type=float, default=2.0, help="请求间隔下限（秒）")
    acc.add_argument("--max-requests", type=int, default=0, help="本次运行请求数安全阀（0=不限）")
    acc.add_argument("--no-pdf", action="store_true", help="不下载 PDF，仅存详情页元数据与 PDF 链接")

    # 后续子命令：chemical / standard ...
    return parser


def _run_regulation(args: argparse.Namespace) -> int:
    crawler = RegulationCrawler(
        min_interval=args.delay,
        max_interval=args.delay + 2.0,
        max_requests=args.max_requests,
    )
    records = crawler.crawl(max_pages=args.max_pages, limit=args.limit, force=args.force)
    logger.info("regulation 采集完成：本次 %d 条", len(records))
    if records:
        sample = records[0]
        logger.info("样例字段: %s", list(sample.keys()))
    return 0 if records or crawler.state.done_count else 1


def _run_gov(args: argparse.Namespace) -> int:
    crawler = GovCrawler(
        min_interval=args.delay,
        max_interval=args.delay + 2.0,
        max_requests=args.max_requests,
    )
    records = crawler.crawl(limit=args.limit, force=args.force)
    logger.info("gov 采集完成：本次 %d 条", len(records))
    if records:
        sample = records[0]
        logger.info(
            "样例: %s | %s | 容器=%s | 字数=%d",
            sample["title"], sample["category"], sample["content_container"], sample["content_len"],
        )
    return 0 if records or crawler.state.done_count else 1


def _run_accident(args: argparse.Namespace) -> int:
    crawler = AccidentCrawler(
        min_interval=args.delay,
        max_interval=args.delay + 2.0,
        max_requests=args.max_requests,
    )
    records = crawler.crawl(limit=args.limit, force=args.force, download_pdf=not args.no_pdf)
    logger.info("accident 采集完成：本次 %d 条", len(records))
    if records:
        sample = records[0]
        logger.info(
            "样例: %s | %s | %s | %d 字",
            sample["title"][:40], sample["level"] or "-",
            sample["category"] or "-", sample.get("content_len", 0),
        )
    return 0 if records or crawler.state.done_count else 1


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "regulation":
        return _run_regulation(args)
    if args.command == "gov":
        return _run_gov(args)
    if args.command == "accident":
        return _run_accident(args)
    logger.error("未知命令: %s", args.command)
    return 2


if __name__ == "__main__":
    sys.exit(main())
