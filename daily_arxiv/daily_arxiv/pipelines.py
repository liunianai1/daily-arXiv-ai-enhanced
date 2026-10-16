# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
import arxiv
import time
import logging
from scrapy.exceptions import DropItem

logger = logging.getLogger(__name__)


class DailyArxivPipeline:
    def __init__(self):
        self.page_size = 100
        # 显式 delay/retries，降低 export.arxiv.org 临时 406/5xx 导致整天空产出的概率
        self.client = arxiv.Client(
            page_size=self.page_size,
            delay_seconds=3.0,
            num_retries=5,
        )
        self.failed = 0
        self.succeeded = 0

    def process_item(self, item: dict, spider):
        item["pdf"] = f"https://arxiv.org/pdf/{item['id']}"
        item["abs"] = f"https://arxiv.org/abs/{item['id']}"
        search = arxiv.Search(id_list=[item["id"]])

        last_err = None
        for attempt in range(1, 4):
            try:
                paper = next(self.client.results(search))
                item["authors"] = [a.name for a in paper.authors]
                item["title"] = paper.title
                item["categories"] = list(paper.categories)
                item["comment"] = paper.comment
                item["summary"] = paper.summary
                self.succeeded += 1
                return item
            except Exception as e:
                last_err = e
                wait = min(30, 3 * attempt)
                logger.warning(
                    "arxiv metadata fetch failed for %s (attempt %s/3): %s; sleep %ss",
                    item.get("id"),
                    attempt,
                    e,
                    wait,
                )
                time.sleep(wait)

        self.failed += 1
        logger.error(
            "Dropping paper %s after retries: %s",
            item.get("id"),
            last_err,
        )
        raise DropItem(f"arxiv metadata unavailable for {item.get('id')}: {last_err}")

    def close_spider(self, spider):
        logger.info(
            "Pipeline finished: succeeded=%s failed=%s",
            self.succeeded,
            self.failed,
        )
        if self.succeeded == 0 and self.failed > 0:
            raise RuntimeError(
                f"All {self.failed} papers failed arxiv metadata fetch "
                "(e.g. HTTP 406). Aborting to avoid empty daily output."
            )
