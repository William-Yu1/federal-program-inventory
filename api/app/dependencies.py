import os
from elasticsearch import Elasticsearch

def get_elasticsearch():
    es_host = os.getenv('ES_HOST', 'elasticsearch')  # Use 'elasticsearch' as the host in Docker Compose
    es_port = int(os.getenv('ES_PORT', '9200'))  # Ensure port is an integer
    es_scheme = os.getenv('ES_SCHEME', 'http')

    # Create the Elasticsearch client
    es = Elasticsearch([{'host': es_host, 'port': es_port, 'scheme': es_scheme}])
    return es