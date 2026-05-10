import pytest
from unittest.mock import MagicMock, patch
from helpers.history import Topic, Message, History

@pytest.fixture
def mock_history():
    history = MagicMock(spec=History)
    history.agent = "test_agent"
    return history

@pytest.fixture
def mock_model_config():
    with patch("plugins._model_config.helpers.model_config.get_chat_model_config") as mock_get_cfg:
        mock_get_cfg.return_value = {
            "ctx_length": 1000,
            "ctx_history": 0.5, # 1000 * 0.5 = 500 max ctx
        }
        yield mock_get_cfg

@patch("helpers.history.messages.truncate_dict_by_ratio")
def test_compress_large_messages(mock_truncate, mock_history, mock_model_config):
    topic = Topic(history=mock_history)

    # max size would be 1000 * 0.5 * 0.5 (if message ratio is 0.5) = 250
    # Let's add messages

    msg1 = Message(ai=False, content="short message")
    msg1.get_tokens = MagicMock(return_value=10)

    msg2 = Message(ai=True, content="very long message " * 100)
    msg2.get_tokens = MagicMock(return_value=300) # This should exceed msg_max_size
    msg2.output_text = MagicMock(return_value="very long message " * 100)

    topic.messages = [msg1, msg2]

    # We need to simulate _is_raw_message to be False for msg2 content
    # In history.py, it imports `_is_raw_message`? Wait, let's see how it's defined
    # We will test first without mocking it if possible.

    mock_truncate.return_value = {"content": "truncated"}

    topic.compress_large_messages(message_ratio=0.5)

    # Check if msg2 was summarized
    assert msg2.summary != ""
    assert msg1.summary == ""
