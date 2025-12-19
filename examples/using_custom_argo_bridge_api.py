import os
import logging
import numpy as np
from openai import AsyncOpenAI
from nano_graphrag import GraphRAG, QueryParam
from nano_graphrag.base import BaseKVStorage
from nano_graphrag._utils import compute_args_hash, wrap_embedding_func_with_attrs

logging.basicConfig(level=logging.WARNING)
logging.getLogger("nano-graphrag").setLevel(logging.INFO)

# Configuration from environment variables
LLM_MODEL = os.getenv("LLM_MODEL", "gpt41")
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "https://apps-dev.inside.anl.gov/argoapi/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_ENDPOINT = os.getenv("EMBEDDING_ENDPOINT", "https://apps-dev.inside.anl.gov/argoapi/v1")

# Embedding model configuration
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
EMBEDDING_MAX_TOKENS = 8192


async def argo_bridge_llm(
    prompt, system_prompt=None, history_messages=[], **kwargs
) -> str:
    """
    Custom LLM function using Argo Bridge API endpoint
    NO retry logic - can handle 15+ minute response times
    """
    openai_async_client = AsyncOpenAI(
        api_key=LLM_API_KEY, 
        base_url=LLM_ENDPOINT
    )
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    
    # Handle caching
    hashing_kv: BaseKVStorage = kwargs.pop("hashing_kv", None)
    messages.extend(history_messages)
    messages.append({"role": "user", "content": prompt})
    
    if hashing_kv is not None:
        args_hash = compute_args_hash(LLM_MODEL, messages)
        if_cache_return = await hashing_kv.get_by_id(args_hash)
        if if_cache_return is not None:
            return if_cache_return["return"]
    
    # Make API call - NO retry logic, NO timeouts
    response = await openai_async_client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        user="chia",
        **kwargs
    )
    
    # Cache response
    if hashing_kv is not None:
        await hashing_kv.upsert(
            {args_hash: {"return": response.choices[0].message.content, "model": LLM_MODEL}}
        )
    
    return response.choices[0].message.content


@wrap_embedding_func_with_attrs(
    embedding_dim=EMBEDDING_DIM,
    max_token_size=EMBEDDING_MAX_TOKENS,
)
async def argo_bridge_embedding(texts: list[str]) -> np.ndarray:
    """
    Custom embedding function using Argo Bridge API endpoint
    NO retry logic - can handle long response times
    """
    openai_async_client = AsyncOpenAI(
        api_key=EMBEDDING_API_KEY, 
        base_url=EMBEDDING_ENDPOINT
    )
    
    # Make API call - NO retry logic, NO timeouts
    response = await openai_async_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
        encoding_format="float",
        user="chia"
    )
    
    return np.array([dp.embedding for dp in response.data])


def remove_if_exist(file):
    if os.path.exists(file):
        os.remove(file)


WORKING_DIR = "./nano_graphrag_cache_argo_bridge"


def query():
    """
    Query the RAG system
    """
    rag = GraphRAG(
        working_dir=WORKING_DIR,
        best_model_func=argo_bridge_llm,
        cheap_model_func=argo_bridge_llm,
        embedding_func=argo_bridge_embedding,
    )
    
    result = rag.query(
        "What are the top themes in this story?", 
        param=QueryParam(mode="global")
    )
    print("Query result:", result)


def insert():
    """
    Insert and process text data
    """
    from time import time
    
    # Load test data
    with open("./tests/mock_data.txt", encoding="utf-8-sig") as f:
        FAKE_TEXT = f.read()
    
    # Clean up old files
    remove_if_exist(f"{WORKING_DIR}/vdb_entities.json")
    remove_if_exist(f"{WORKING_DIR}/kv_store_full_docs.json")
    remove_if_exist(f"{WORKING_DIR}/kv_store_text_chunks.json")
    remove_if_exist(f"{WORKING_DIR}/kv_store_community_reports.json")
    remove_if_exist(f"{WORKING_DIR}/graph_chunk_entity_relation.graphml")
    
    # Initialize RAG with caching enabled
    rag = GraphRAG(
        working_dir=WORKING_DIR,
        enable_llm_cache=True,
        best_model_func=argo_bridge_llm,
        cheap_model_func=argo_bridge_llm,
        embedding_func=argo_bridge_embedding,
    )
    
    # Process the text
    start = time()
    rag.insert(FAKE_TEXT)
    print("Indexing time:", time() - start)




if __name__ == "__main__":
    # Check if environment variables are set
    if not LLM_API_KEY:
        print("Error: LLM_API_KEY environment variable not set")
        exit(1)
    
    if not EMBEDDING_API_KEY:
        print("Error: EMBEDDING_API_KEY environment variable not set")
        exit(1)
    
    print(f"Using LLM: {LLM_MODEL} at {LLM_ENDPOINT}")
    print(f"Using Embedding: {EMBEDDING_MODEL} at {EMBEDDING_ENDPOINT}")
    print("Note: No retry logic - can handle 15+ minute response times")
    
    # Process text
    insert()
    query()
