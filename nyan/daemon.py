import json
import os
from collections import Counter
from time import sleep
from typing import Counter as CounterT
from typing import Dict, Any, Optional, List, cast

from sklearn.metrics.pairwise import cosine_similarity

from nyan.annotator import Annotator
from nyan.channels import Channels
from nyan.client import TelegramClient
from nyan.clusterer import Clusterer
from nyan.clusters import Clusters, Cluster
from nyan.document import (
    read_documents_file,
    read_documents_mongo,
    Document,
    read_annotated_documents_mongo,
    write_annotated_documents_mongo,
)
from nyan.ranker import Ranker
from nyan.renderer import Renderer
from nyan.util import get_current_ts, ts_to_dt


class Daemon:
    def __init__(
        self,
        client_config_path: str,
        annotator_config_path: str,
        clusterer_config_path: str,
        ranker_config_path: str,
        channels_info_path: str,
        renderer_config_path: str,
        daemon_config_path: str,
        skip_send: bool,
    ) -> None:
        self.client = TelegramClient(client_config_path)
        self.channels = Channels(channels_info_path)
        self.annotator = Annotator(annotator_config_path, self.channels)
        self.clusterer = Clusterer(clusterer_config_path)
        self.renderer = Renderer(renderer_config_path, self.channels)
        self.ranker = Ranker(ranker_config_path)
        self.skip_send = skip_send

        assert os.path.exists(daemon_config_path)
        with open(daemon_config_path) as r:
            self.config: Dict[str, Any] = json.load(r)

    def run(
        self,
        input_path: Optional[str],
        mongo_config_path: Optional[str],
        posted_clusters_path: Optional[str],
    ) -> None:
        while True:
            self.__call__(input_path, mongo_config_path, posted_clusters_path)
            sleep(30)

    def __call__(
        self,
        input_path: Optional[str],
        mongo_config_path: Optional[str],
        posted_clusters_path: Optional[str],
    ) -> None:
        assert (
            input_path and not mongo_config_path or mongo_config_path and not input_path
        )
        if input_path and not os.path.exists(input_path):
            print("No input documents!")
            return

        print("===== New iteration =====")
        clusters_offset = self.config["clusters_offset"]
        posted_clusters = self.load_posted_clusters(
            mongo_config_path, posted_clusters_path, clusters_offset
        )

        documents_offset = self.config["documents_offset"]
        try:
            docs = self.read_documents(input_path, documents_offset, mongo_config_path)
        except Exception as e:
            print(e)
            print("Waiting for correct documents...")
            return
        if not docs:
            print("Waiting for documents...")
            sleep(10)
            return
        self.print_bad_channels(docs)
        annotated_docs = self.annotate_documents(docs, mongo_config_path)

        updates_count = posted_clusters.update_documents(annotated_docs)
        print("{} updated documents".format(updates_count))

        new_clusters: List[Cluster] = self.clusterer(annotated_docs)
        print("{} clusters overall".format(len(new_clusters)))

        ranked_clusters: Dict[str, List[Cluster]] = self.ranker(new_clusters)
        num_clusters = sum([len(cl) for cl in ranked_clusters.values()])
        print("{} clusters in all issues after filtering".format(num_clusters))

        print()
        for issue, clusters in ranked_clusters.items():
            for cluster in clusters:
                if not self.skip_send:
                    self.send_cluster(
                        cluster,
                        issue,
                        posted_clusters,
                        posted_clusters_path,
                        mongo_config_path,
                    )
                else:
                    posted_clusters.add(cluster)

        print()
        if posted_clusters_path:
            posted_clusters.save(posted_clusters_path)
            print("{} clusters saved to file".format(len(posted_clusters)))
        if mongo_config_path:
            saved_count = posted_clusters.save_to_mongo(mongo_config_path)
            print("{} clusters saved to Mongo".format(saved_count))
            print()

    def load_posted_clusters(
        self,
        mongo_config_path: Optional[str],
        posted_clusters_path: Optional[str],
        clusters_offset: int,
    ) -> Clusters:
        posted_clusters = Clusters()
        if mongo_config_path:
            print("Reading clusters from Mongo")
            posted_clusters = Clusters.load_from_mongo(
                mongo_config_path, get_current_ts(), clusters_offset
            )
        elif posted_clusters_path and os.path.exists(posted_clusters_path):
            print("Reading clusters from file")
            posted_clusters = Clusters.load(posted_clusters_path)
        print("{} clusters loaded".format(len(posted_clusters)))
        return posted_clusters

    def read_documents(
        self,
        input_path: Optional[str],
        documents_offset: int,
        mongo_config_path: Optional[str],
    ) -> List[Document]:
        if input_path and os.path.exists(input_path):
            print("Reading docs from file")
            docs = read_documents_file(input_path, get_current_ts(), documents_offset)
        elif mongo_config_path:
            print("Reading docs from Mongo")
            docs = read_documents_mongo(
                mongo_config_path, get_current_ts(), documents_offset
            )
        else:
            raise AssertionError()
        print("{} docs loaded".format(len(docs)))
        max_pub_time = ts_to_dt(max([d.pub_time for d in docs])).strftime(
            "%d-%m-%y %H:%M"
        )
        print("Last document: {}".format(max_pub_time))
        return docs

    def print_bad_channels(self, docs: List[Document]) -> None:
        doc_channels_cnt: CounterT[str] = Counter()
        for doc in docs:
            doc_channels_cnt[doc.channel_id] += 1
        for channel_id, channel in self.channels:
            cnt = doc_channels_cnt.get(channel_id, 0)
            if cnt <= 1 and not channel.disabled and channel.issue == "main":
                print("Warning: {} docs from channel {}".format(cnt, channel_id))

    def annotate_documents(
        self, docs: List[Document], mongo_config_path: Optional[str]
    ) -> List[Document]:
        all_annotated_docs: List[Document] = []
        remaining_docs = docs
        if mongo_config_path:
            all_annotated_docs, remaining_docs = read_annotated_documents_mongo(
                mongo_config_path, docs
            )
            print(
                "{} docs already annotated, {} docs to annotate".format(
                    len(all_annotated_docs), len(remaining_docs)
                )
            )

        if remaining_docs:
            annotated_docs = self.annotator(remaining_docs)
            print("{} docs annotated".format(len(annotated_docs)))
            all_annotated_docs += annotated_docs

        if mongo_config_path and remaining_docs:
            write_annotated_documents_mongo(mongo_config_path, annotated_docs)

        final_docs = self.annotator.postprocess(all_annotated_docs)
        print("{} docs before clustering".format(len(final_docs)))

        return final_docs

    def send_cluster(
        self,
        cluster: Cluster,
        issue_name: str,
        posted_clusters: Clusters,
        posted_clusters_path: Optional[str],
        mongo_config_path: Optional[str],
    ) -> None:
        sleep_time = self.config["sleep_time"]
        max_time_updated = self.config["max_time_updated"]

        posted_cluster = posted_clusters.find_similar(
            cluster,
            issue_name,
            min_intersection_ratio=self.config["similar_min_intersection_ratio"],
        )
        if posted_cluster:
            message = posted_cluster.get_issue_message(issue_name)
            assert message
            discussion_message = self.client.get_discussion(message)

            new_docs_pub_time = 0
            for doc in cluster.docs:
                if not posted_cluster.has(doc):
                    posted_cluster.add(doc)
                    discussion_text = self.renderer.render_discussion_message(doc)
                    self.client.send_discussion_message(
                        discussion_text, discussion_message
                    )
                    new_docs_pub_time = max(doc.pub_time, new_docs_pub_time)
                    sleep(sleep_time)

            current_ts = get_current_ts()
            time_diff = abs(current_ts - posted_cluster.pub_time_percentile)
            if time_diff < max_time_updated and posted_cluster.changed():
                posted_cluster.saved_diff = None
                cluster_text = self.renderer.render_cluster(posted_cluster, issue_name)
                print(
                    "Update message {} at {}: {}".format(
                        message.message_id, message.issue, posted_cluster.cropped_title
                    )
                )
                print("Discussion message id: {}".format(discussion_message.message_id))

                is_caption = ((bool(posted_cluster.images) or bool(posted_cluster.videos))
                              and not message.forced_no_media)
                self.client.update_message(message, cluster_text, is_caption)

            return

        cluster_text = self.renderer.render_cluster(cluster, issue_name)
        print("New cluster in {}: {}".format(issue_name, cluster.cropped_title))

        self.client.update_discussion_mapping(issue_name)

        reply_to = self.calc_reply_to(cluster, posted_clusters, issue_name)
        message = self.client.send_message(
            cluster_text,
            issue_name,
            photos=cluster.images,
            videos=cluster.videos,
            reply_to=reply_to,
        )
        if message is None:
            return

        cluster.create_time = get_current_ts()
        cluster.messages.append(message)
        posted_clusters.add(cluster)

        print("Message id: {}, saving".format(message.message_id))
        if posted_clusters_path:
            posted_clusters.save(posted_clusters_path)
        if mongo_config_path:
            posted_clusters.save_to_mongo(mongo_config_path)

        self.client.update_discussion_mapping(issue_name)
        discussion_message = self.client.get_discussion(message)
        print("Discussion message id: {}".format(discussion_message.message_id))

        for doc in cluster.docs:
            discussion_text = self.renderer.render_discussion_message(doc)
            self.client.send_discussion_message(discussion_text, discussion_message)
            sleep(sleep_time)
        print()
        return

    def calc_reply_to(
        self, cluster: Cluster, posted_clusters: Clusters, issue_name: str
    ) -> Optional[int]:
        threshold = float(self.config["related_threshold"])

        current_ts = get_current_ts()
        clusters = posted_clusters.get_embedded_clusters(current_ts, issue_name)
        if not clusters:
            return None

        pivot_embedding = [cluster.annotation_doc.embedding]
        embeddings = [cl.embedding for cl in clusters]
        sims = cosine_similarity(pivot_embedding, embeddings)[0]

        max_index = sims.argmax()
        max_sim = sims[max_index]
        best_cluster = clusters[max_index]
        print(
            "Closest cluster:",
            max_sim,
            cluster.cropped_title,
            best_cluster.cropped_title,
        )

        if best_cluster.pub_time_percentile > cluster.pub_time_percentile:
            return None

        if max_sim < threshold:
            return None

        for m in best_cluster.messages:
            if m.issue == issue_name:
                return cast(int, m.message_id)
        return None
