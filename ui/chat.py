import streamlit as st
from service.tool_call import LLMService

def render():
    st.subheader("Simple chat")

    # Accept user input
    input_container = st.container()
    # Display chat messages from history on app rerun
    chat_container = st.container()
    prompt = None
    response = None
    with input_container:
        if prompt := st.chat_input("What is up?"):
            # Display user message in chat message container
            with st.chat_message("user"):
                st.markdown(prompt)

            # Add a spinner while waiting for the response
            with st.spinner("Processing..."):
                # Process user input with LLMService
                llm_service = LLMService()
                response = llm_service.invoke_llm(prompt)

            # Display assistant response in chat message container
            with st.chat_message("assistant"):
                st.markdown(response)
            
    

    with chat_container:
        if "messages" not in st.session_state:  # Check if messages are not empty
            st.session_state.messages = []
        else:
            st.text("Chat History:")
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
            # Add user message and assistant response to chat history
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.session_state.messages.append({"role": "assistant", "content": response})