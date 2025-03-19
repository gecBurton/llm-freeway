# LLM Freeway

llm-freeway is a simple, secure and open-source proxy server for litellm.

## features

* chat-completion
  * authorization via jwt
  * streaming and non-streaming
* user management
  * Create Read Update and Delete users
  * Generate tokens for use with chat-completion 
  * Restrict user access by:
    * tokens-per-minute
    * requests-per-minute
* logs
  * access to your own logs
  * access all logs if you are and admin


## how to run

* locally, using sqlite `make web`
* via docker