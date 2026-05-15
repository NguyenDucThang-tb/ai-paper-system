from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.config import settings
from storage.graph_db.neo4j_client import Neo4jClient, Neo4jConfig

router = APIRouter()


@router.get("/neo4j-health")
def neo4j_health(current_user=Depends(get_current_user)):
    is_admin = str(getattr(current_user, "role", "")).lower() == "admin"
    is_dev_env = str(settings.ENV).lower() in {"development", "dev", "local"}
    if not (is_admin or is_dev_env):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    uri = (settings.NEO4J_URI or "").strip()
    username = (settings.NEO4J_USERNAME or "").strip()
    password = (settings.NEO4J_PASSWORD or "").strip()
    database = (settings.NEO4J_DATABASE or "neo4j").strip()

    if not uri:
        return {
            "configured": False,
            "connected": False,
            "database": database,
            "node_count": None,
            "relationship_count": None,
            "error": "Missing NEO4J_URI",
        }
    if not username:
        return {
            "configured": False,
            "connected": False,
            "database": database,
            "node_count": None,
            "relationship_count": None,
            "error": "Missing NEO4J_USERNAME/NEO4J_USER",
        }
    if not password:
        return {
            "configured": False,
            "connected": False,
            "database": database,
            "node_count": None,
            "relationship_count": None,
            "error": "Missing NEO4J_PASSWORD",
        }

    client = Neo4jClient(
        Neo4jConfig(
            uri=uri,
            username=username,
            password=password,
            database=database,
        )
    )
    try:
        client.connect()
        nodes = client.execute_read("MATCH (n) RETURN count(n) AS node_count")
        rels = client.execute_read("MATCH ()-[r]->() RETURN count(r) AS relationship_count")
        return {
            "configured": True,
            "connected": True,
            "database": database,
            "node_count": int(nodes[0]["node_count"]) if nodes else 0,
            "relationship_count": int(rels[0]["relationship_count"]) if rels else 0,
            "error": None,
        }
    except Exception as ex:
        return {
            "configured": True,
            "connected": False,
            "database": database,
            "node_count": None,
            "relationship_count": None,
            "error": str(ex),
        }
    finally:
        try:
            client.close()
        except Exception:
            pass
