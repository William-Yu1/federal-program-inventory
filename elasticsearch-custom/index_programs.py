from elasticsearch import Elasticsearch, helpers
import json
import os
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Elasticsearch client connected to the service
es = Elasticsearch(hosts=["http://elasticsearch:9200"])

def delete_index(index_name):
    """Delete index if it exists"""
    try:
        if es.indices.exists(index=index_name):
            logger.info(f"Deleting existing index '{index_name}'")
            es.indices.delete(index=index_name)
            logger.info(f"Successfully deleted index '{index_name}'")
            return True
        else:
            logger.info(f"Index '{index_name}' does not exist, no need to delete")
            return False
    except Exception as e:
        logger.error(f"Error deleting index: {str(e)}")
        raise

def create_index_with_mapping(index_name):
    """Create new index with mapping"""
    mapping = {
        "settings": {
            "index": {
                "query": {
                    "default_field": ["title", "objectives", "cfda", "popularName"]
                }
            }
        },
        "mappings": {
            "dynamic": "strict",  # Prevent automatic field creation
            "properties": {
                "cfda": {
                    "type": "text",
                    "analyzer": "english",  # Add stemming
                    "fields": {
                        "keyword": {
                            "type": "keyword"
                        }
                    }
                },
                "title": {
                    "type": "text",
                    "analyzer": "english",  # Add stemming
                    "fields": {
                        "keyword": {
                            "type": "keyword"
                        }
                    }
                },
                "agency": {
                    "type": "nested",
                    "properties": {
                        "title": {
                            "type": "text",
                            "fields": {
                                "keyword": {
                                    "type": "keyword"
                                }
                            }
                        },
                        "subAgency": {
                            "type": "nested",
                            "properties": {
                                "title": {
                                    "type": "text",
                                    "fields": {
                                        "keyword": {
                                            "type": "keyword"
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "obligations": {
                    "type": "float"
                },
                "objectives": {
                    "type": "text",
                    "analyzer": "english",  # Add stemming
                    "fields": {
                        "keyword": {
                            "type": "keyword"
                        }
                    }
                },
                "popularName": {
                    "type": "text",
                    "analyzer": "english",  # Add stemming
                    "fields": {
                        "keyword": {
                            "type": "keyword"
                        }
                    }
                },
                "permalink": {
                    "type": "text",
                    "index": False
                },
                "assistanceTypes": {
                    "type": "keyword"
                },
                "applicantTypes": {
                    "type": "keyword",
                    "index": True
                },
                "categories": {
                    "type": "nested",
                    "properties": {
                        "title": {
                            "type": "text",
                            "fields": {
                                "keyword": {
                                    "type": "keyword"
                                }
                            }
                        },
                        "subCategory": {
                            "type": "nested",
                            "properties": {
                                "title": {
                                    "type": "text",
                                    "fields": {
                                        "keyword": {
                                            "type": "keyword"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    try:
        logger.info(f"Creating new index '{index_name}' with mapping")
        es.indices.create(index=index_name, body=mapping)
        logger.info(f"Successfully created index '{index_name}'")
        
        # Verify the mapping
        actual_mapping = es.indices.get_mapping(index=index_name)
        logger.info(f"Verified mapping for index '{index_name}'")
        return True
    except Exception as e:
        logger.error(f"Error creating index: {str(e)}")
        raise

def load_data(json_file, index_name):
    """Load data into index"""
    try:
        # Read JSON file
        with open(json_file, 'r') as f:
            programs = json.load(f)
        
        logger.info(f"Loaded {len(programs)} programs from {json_file}")

        # Prepare bulk actions
        actions = []
        for program in programs:
            action = {
                "_op_type": "index",
                "_index": index_name,
                "_id": program['cfda'],
                "_source": program
            }
            actions.append(action)

        # Perform bulk indexing
        success, failed = helpers.bulk(es, actions, stats_only=True)
        logger.info(f"Bulk indexing completed: {success} succeeded, {failed} failed")

        # Refresh index to make documents searchable immediately
        es.indices.refresh(index=index_name)
        
        # Verify document count
        count = es.count(index=index_name)
        logger.info(f"Total documents in index after loading: {count['count']}")
        return count['count']

    except Exception as e:
        logger.error(f"Error loading data: {str(e)}")
        raise

def verify_index(index_name):
    """Verify index contents"""
    try:
        # Check document count
        count = es.count(index=index_name)
        logger.info(f"Document count in index: {count['count']}")
        
        # Get a sample document
        sample = es.search(index=index_name, body={
            "query": {"match_all": {}},
            "size": 1
        })
        
        if sample['hits']['hits']:
            logger.info("Successfully retrieved sample document")
            logger.debug(f"Sample document: {sample['hits']['hits'][0]['_source']}")
        else:
            logger.warning("No documents found in index")
            
        return count['count']
    except Exception as e:
        logger.error(f"Error verifying index: {str(e)}")
        raise

if __name__ == "__main__":
    try:
        index_name = "programs"
        
        # Step 1: Delete existing index
        logger.info("Step 1: Cleaning up old index")
        delete_index(index_name)
        
        # Step 2: Create new index with mapping
        logger.info("Step 2: Creating new index with mapping")
        create_index_with_mapping(index_name)
        
        # Step 3: Load data
        logger.info("Step 3: Loading data")
        json_file_path = os.path.join('/app/data', 'programs-table.json')
        doc_count = load_data(json_file_path, index_name)
        
        # Step 4: Verify
        logger.info("Step 4: Verifying index")
        final_count = verify_index(index_name)
        
        if final_count > 0:
            logger.info(f"Successfully indexed {final_count} documents")
        else:
            logger.error("No documents were indexed")
            
    except Exception as e:
        logger.error(f"Indexing process failed: {str(e)}")
        raise