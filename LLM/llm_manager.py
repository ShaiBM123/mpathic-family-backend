from transformers import GPTNeoForCausalLM, AutoTokenizer

# tokenizer = AutoTokenizer.from_pretrained("facebook/opt-1.3b")
# model = GPTNeoForCausalLM.from_pretrained("facebook/opt-1.3b")

from transformers import pipeline

# Load the DialoGPT conversational pipeline
chatbot = pipeline('conversational', model="microsoft/DialoGPT-medium")

# Initiate a conversation
conv = Conversation("I'm feeling frustrated because no one listens to me.")
response = chatbot(conv)

# Get the chatbot's response
print(response)
