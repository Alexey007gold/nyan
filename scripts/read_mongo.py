from nyan.mongo import get_documents_collection, get_annotated_documents_collection


def examples():
    collection = get_documents_collection("../configs/mongo_config.json")
    annotated = get_annotated_documents_collection("../configs/mongo_config.json")
    list(collection.find({"text": {"$regex": "рассказываем читателям", "$options": "i"}}))
    print()
