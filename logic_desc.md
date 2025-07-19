Configs:
-
- channels.json list of channels in format
```
{
   "name": "mediazzzona",
   "groups": {
     "main": "blue",
     "tech": "other"
   },
   "alias": "Медиазона",
   "issue": "main",
   "recrawl_time": 300
}
```
- client_config.json to what target channel each news category should be posted
- annotator_config.json params for message/text processing
- renderer_config.json params for timezone and cluster template
- daemon_config.json news aggregation params



Logic
-
`scrapy` tool is used for crawling telegram channels.
It is used with custom spider implementation in crawler/spiders/telegram.py
It loads web version of channels, parses the details, stores them to mongo
Or can store as `.jsonl` files (configured in `crawler/settings.py`)


Main logic is run with
`send.sh`
which invokes
`python3 -m nyan.send`
with some arguments. The arguments can point it to use mongodb for storage, 
or files.

- load documents (news) from the storage with pub_time threshold of last 24 hours (daemon.py)
- warn about channels with less than 2 messages
- annotation logic
  - load already annotated docs (from mongo only, `annotated_documents` collection)
  - filter docs that are being processed leaving only not annotated, or requiring re-annotation (if text has changed, or code version increased)
  - update fetch_time and views for already annotated docs
  - annotate
    - process_channels_info
      - set groups, issue, channel_title (channel metadata)
    - clean_text, save to doc.patched_text
      - skip text completely if contains some keywords set in `skip_substrings`
      - remove matches set in `rm_substrings`
      - remove emojis
      - remove hashtags
      - remove mentions (of users)
      - remove urls
      - fix punctuation
      - skip text completely if contains some keywords set in `skip_substrings`
      - remove matches set in `rm_substrings`
    - tokenize, save to doc.tokens
      - segment
      - tag morphology
      - lemmatize
    - normalize_links
    - check if contains obscene tokens, mark doc.has_obscene
    - detect text language
    - remove images if match given in config with a similarity threshold
    - calc embeddings, save to doc.embedding
    - detect text category using embeddings (local model)
  - save newly annotated docs to mongo
  - filter out docs smaller than 12 chars, category `not_news`
  - clusterization logic (Groups similar documents together)
    - loads posted clusters from mongo (`clusters` collection)
    - updates existing docs in clusters
    - collects clusters from ALL annotated docs (loaded from mongo and new)
    - ranks clusters
      - processes them by `issue`
        - chooses clusters passing `min_channels` threshold, having russian text, and below `max_age_minutes` threshold
          - age is calculated as 20th percentile by doc `pub_time`
        - if there are less than 3 of such, then take what is left and skip next step
        - filters them by views using percentiles
  - send the clusters
  - save clusters to file or mongo
