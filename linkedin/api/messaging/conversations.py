# linkedin/api/messaging/conversations.py
"""Retrieve conversations and messages via Voyager Messaging GraphQL API."""
import logging

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from linkedin.api.client import PlaywrightLinkedinAPI
from linkedin.api.messaging.utils import encode_urn, check_response

logger = logging.getLogger(__name__)

_GRAPHQL_BASE = "https://www.linkedin.com/voyager/api/voyagerMessagingGraphQL/graphql"
_CONVERSATIONS_QUERY_ID = "messengerConversations.0d5e6781bbee71c3e51c8843c6519f48"
_MESSAGES_QUERY_ID = "messengerMessages.5846eeb71c981f11e0134cb6626cc314"


def _graphql_headers(api: PlaywrightLinkedinAPI) -> dict:
    headers = {**api.headers}
    headers["accept"] = "application/graphql"
    return headers


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(IOError),
    reraise=True,
)
def fetch_conversations(api: PlaywrightLinkedinAPI, mailbox_urn: str, max_pages: int = 5) -> list[dict]:
    """Fetch recent conversations list, with pagination support."""
    conversations = []
    paging_token = None
    
    for _ in range(max_pages):
        variables = f"(mailboxUrn:{encode_urn(mailbox_urn)})"
        if paging_token:
            variables = f"(mailboxUrn:{encode_urn(mailbox_urn)},pagingToken:{encode_urn(paging_token)})"
            
        url = f"{_GRAPHQL_BASE}?queryId={_CONVERSATIONS_QUERY_ID}&variables={variables}"
        res = api.get(url, headers=_graphql_headers(api))
        check_response(res, "fetch_conversations")
        
        data = res.json()
        data_content = data.get("data", {})
        result_node = next(iter(data_content.values()), {}) if data_content else {}
        items = result_node.get("elements", [])
        conversations.extend(items)
        
        paging_token = result_node.get("pagingToken")
        if not paging_token:
            break
            
    return conversations


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(IOError),
    reraise=True,
)
def fetch_messages(api: PlaywrightLinkedinAPI, conversation_urn: str, max_pages: int = 5) -> list[dict]:
    """Fetch messages for a conversation, with pagination support."""
    messages = []
    paging_token = None
    
    for _ in range(max_pages):
        variables = f"(conversationUrn:{encode_urn(conversation_urn)})"
        if paging_token:
            variables = f"(conversationUrn:{encode_urn(conversation_urn)},pagingToken:{encode_urn(paging_token)})"
            
        url = f"{_GRAPHQL_BASE}?queryId={_MESSAGES_QUERY_ID}&variables={variables}"
        res = api.get(url, headers=_graphql_headers(api))
        check_response(res, "fetch_messages")
        
        data = res.json()
        data_content = data.get("data", {})
        
        # Robust key handling: Voyager can use both URN-based or SyncToken-based keys
        result_node = data_content.get("messengerMessagesByConversationUrn") or \
                      data_content.get("messengerMessagesBySyncToken") or \
                      next(iter(data_content.values()), {})
                      
        items = result_node.get("elements", [])
        messages.extend(items)
        
        paging_token = result_node.get("pagingToken")
        if not paging_token:
            break
            
    return messages



if __name__ == "__main__":
    import json
    from linkedin.browser.registry import cli_parser, cli_session

    parser = cli_parser("Fetch raw Voyager messaging data")
    parser.add_argument("--conversations", action="store_true", help="List recent conversations")
    parser.add_argument("--messages", default=None, metavar="CONVERSATION_URN", help="Fetch messages for a conversation URN")
    args = parser.parse_args()
    session = cli_session(args)
    session.ensure_browser()

    api = PlaywrightLinkedinAPI(session=session)

    if args.conversations:
        mailbox_urn = session.self_profile["urn"]
        elements = fetch_conversations(api, mailbox_urn)
        print(f"Got {len(elements)} conversations:\n")
        for conv in elements:
            urn = conv.get("entityUrn", "")
            participants = []
            for p in conv.get("conversationParticipants", []):
                member = p.get("participantType", {}).get("member", {})
                first = (member.get("firstName") or {}).get("text", "")
                last = (member.get("lastName") or {}).get("text", "")
                name = f"{first} {last}".strip()
                if name:
                    participants.append(name)
            print(f"  {', '.join(participants)}")
            print(f"    URN: {urn}\n")

    elif args.messages:
        messages = fetch_messages(api, args.messages)
        print(f"Fetched {len(messages)} messages.")
        print(json.dumps(messages, indent=2, default=str)[:10000])


    else:
        parser.print_help()
