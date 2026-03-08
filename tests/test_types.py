from ker.types import InboundMessage, OutboundMessage, ProviderBlock, ProviderResponse


def test_inbound_message_defaults():
    msg = InboundMessage(text="hello", sender_id="user1")
    assert msg.text == "hello"
    assert msg.channel == ""
    assert msg.user == ""
    assert msg.session_name == "default"


def test_outbound_message():
    msg = OutboundMessage(text="response", channel="cli", user="user1")
    assert msg.text == "response"


def test_provider_response():
    block = ProviderBlock(type="text", text="hello")
    response = ProviderResponse(stop_reason="end_turn", content=[block])
    assert response.stop_reason == "end_turn"
    assert len(response.content) == 1
