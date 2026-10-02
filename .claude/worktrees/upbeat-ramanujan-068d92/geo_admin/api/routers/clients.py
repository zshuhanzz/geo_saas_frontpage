"""
Clients Router - CRUD operations for geo_clients, geo_client_peers, geo_client_domains

Provides endpoints for managing clients, their competitors (peers), and owned domains.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
from sqlalchemy import select, insert, update, delete
from database import database, geo_clients, geo_client_peers, geo_client_domains

router = APIRouter(prefix="/clients", tags=["Clients"])


# --- Pydantic Models ---

class PeerCreate(BaseModel):
    peer_name: str

class DomainCreate(BaseModel):
    domain: str
    is_primary: bool = False

class ClientCreate(BaseModel):
    name: str
    peers: List[str] = []
    domains: List[DomainCreate] = []

class ClientUpdate(BaseModel):
    name: Optional[str] = None

class ClientResponse(BaseModel):
    id: UUID
    name: str
    peers: List[str]
    domains: List[dict]


# --- Client CRUD ---

@router.get("", response_model=List[ClientResponse])
async def list_clients(search: Optional[str] = None):
    """List all clients with their peers and domains. Supports optional search filter."""
    query = select(geo_clients).order_by(geo_clients.c.name)
    if search:
        query = query.where(geo_clients.c.name.ilike(f"%{search}%"))
    
    clients = await database.fetch_all(query)
    
    result = []
    for client in clients:
        client_id = client["id"]
        
        # Fetch peers
        peers_query = select(geo_client_peers.c.peer_name).where(
            geo_client_peers.c.client_id == client_id
        )
        peers = await database.fetch_all(peers_query)
        peer_names = [p["peer_name"] for p in peers]
        
        # Fetch domains
        domains_query = select(geo_client_domains).where(
            geo_client_domains.c.client_id == client_id
        )
        domains = await database.fetch_all(domains_query)
        domain_list = [{"domain": d["domain"], "is_primary": d["is_primary"]} for d in domains]
        
        result.append({
            "id": client_id,
            "name": client["name"],
            "peers": peer_names,
            "domains": domain_list
        })
    
    return result


@router.post("", response_model=ClientResponse, status_code=201)
async def create_client(data: ClientCreate):
    """Create a new client with optional peers and domains."""
    # Check for duplicate name
    existing = await database.fetch_one(
        select(geo_clients).where(geo_clients.c.name == data.name)
    )
    if existing:
        raise HTTPException(status_code=400, detail="Client with this name already exists")
    
    # Insert client
    result = await database.fetch_one(
        insert(geo_clients).values(name=data.name).returning(geo_clients.c.id)
    )
    client_id = result["id"]
    
    # Insert peers
    for peer_name in data.peers:
        await database.execute(
            insert(geo_client_peers).values(client_id=client_id, peer_name=peer_name)
        )
    
    # Insert domains
    for domain in data.domains:
        await database.execute(
            insert(geo_client_domains).values(
                client_id=client_id,
                domain=domain.domain,
                is_primary=domain.is_primary
            )
        )
    
    return {
        "id": client_id,
        "name": data.name,
        "peers": data.peers,
        "domains": [{"domain": d.domain, "is_primary": d.is_primary} for d in data.domains]
    }


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(client_id: UUID):
    """Get a single client by ID with peers and domains."""
    client = await database.fetch_one(
        select(geo_clients).where(geo_clients.c.id == client_id)
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Fetch peers
    peers = await database.fetch_all(
        select(geo_client_peers.c.peer_name).where(geo_client_peers.c.client_id == client_id)
    )
    
    # Fetch domains
    domains = await database.fetch_all(
        select(geo_client_domains).where(geo_client_domains.c.client_id == client_id)
    )
    
    return {
        "id": client["id"],
        "name": client["name"],
        "peers": [p["peer_name"] for p in peers],
        "domains": [{"domain": d["domain"], "is_primary": d["is_primary"]} for d in domains]
    }


@router.put("/{client_id}", response_model=ClientResponse)
async def update_client(client_id: UUID, data: ClientUpdate):
    """Update client name."""
    client = await database.fetch_one(
        select(geo_clients).where(geo_clients.c.id == client_id)
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    if data.name:
        await database.execute(
            update(geo_clients).where(geo_clients.c.id == client_id).values(name=data.name)
        )
    
    return await get_client(client_id)


@router.delete("/{client_id}", status_code=204)
async def delete_client(client_id: UUID):
    """Delete a client and all associated peers/domains (CASCADE)."""
    client = await database.fetch_one(
        select(geo_clients).where(geo_clients.c.id == client_id)
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    await database.execute(
        delete(geo_clients).where(geo_clients.c.id == client_id)
    )
    return None


# --- Peer Management ---

@router.post("/{client_id}/peers", status_code=201)
async def add_peer(client_id: UUID, data: PeerCreate):
    """Add a peer to a client."""
    client = await database.fetch_one(
        select(geo_clients).where(geo_clients.c.id == client_id)
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Check for duplicate
    existing = await database.fetch_one(
        select(geo_client_peers).where(
            geo_client_peers.c.client_id == client_id,
            geo_client_peers.c.peer_name == data.peer_name
        )
    )
    if existing:
        raise HTTPException(status_code=400, detail="Peer already exists for this client")
    
    await database.execute(
        insert(geo_client_peers).values(client_id=client_id, peer_name=data.peer_name)
    )
    return {"message": "Peer added"}


@router.delete("/{client_id}/peers/{peer_name}", status_code=204)
async def remove_peer(client_id: UUID, peer_name: str):
    """Remove a peer from a client."""
    await database.execute(
        delete(geo_client_peers).where(
            geo_client_peers.c.client_id == client_id,
            geo_client_peers.c.peer_name == peer_name
        )
    )
    return None


# --- Domain Management ---

@router.post("/{client_id}/domains", status_code=201)
async def add_domain(client_id: UUID, data: DomainCreate):
    """Add a domain to a client."""
    client = await database.fetch_one(
        select(geo_clients).where(geo_clients.c.id == client_id)
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Check for duplicate
    existing = await database.fetch_one(
        select(geo_client_domains).where(
            geo_client_domains.c.client_id == client_id,
            geo_client_domains.c.domain == data.domain
        )
    )
    if existing:
        raise HTTPException(status_code=400, detail="Domain already exists for this client")
    
    await database.execute(
        insert(geo_client_domains).values(
            client_id=client_id,
            domain=data.domain,
            is_primary=data.is_primary
        )
    )
    return {"message": "Domain added"}


@router.delete("/{client_id}/domains/{domain}", status_code=204)
async def remove_domain(client_id: UUID, domain: str):
    """Remove a domain from a client."""
    await database.execute(
        delete(geo_client_domains).where(
            geo_client_domains.c.client_id == client_id,
            geo_client_domains.c.domain == domain
        )
    )
    return None
