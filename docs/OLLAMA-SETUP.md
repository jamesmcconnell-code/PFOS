# Optional local AI with Ollama

PFOS can use an Ollama model for app help and explanations of PFOS-calculated
spending summaries and What If scenarios. The integration is opt-in. PFOS sends
chat context and requested calculation aggregates to Ollama at
`http://127.0.0.1:11434`; PFOS does not send them to a cloud AI provider or save
chat history. PFOS computes all financial results and displays those results
separately from the model's qualitative explanation.

## Privacy boundary

Ollama must run on the same trusted computer or server as the PFOS API. PFOS
connects only to loopback and refuses redirects. In the desktop app, the
bundled API and Ollama run on your Mac. In local development, they run on the
same development machine. A remotely hosted PFOS API cannot reach Ollama on a
user's laptop through this integration. Do not enable this setting on a remote
backend unless Ollama is intentionally installed on that same trusted host.

PFOS does not control Ollama's independent cloud configuration. For local-only
inference, disable Ollama cloud features as described below. Turning that off
also disables Ollama cloud models and Ollama web search. Even with cloud
features disabled, installing/updating Ollama and downloading model weights
requires internet access; inference can run offline after that content is
available locally.

## Install Ollama and download a local model

1. Check the current [Ollama macOS requirements](https://ollama.com/download/mac)
   and install Ollama from the official download. The current macOS app requires
   macOS 14 Sonoma or newer.
2. Open Ollama and download an instruction-following model that supports tool
   calling. PFOS's tools require the model to request structured functions. For
   example, Ollama currently lists `qwen2.5:7b` as a tool-capable model; its
   quantized download is about 4.7 GB and its Ollama library page reports the
   Apache 2.0 license. Model licenses, disk sizes, and compatibility can change;
   review the model's current [Ollama library entry](https://ollama.com/library/qwen2.5:7b)
   and license before choosing it.

   To download that example in Terminal:

   ```sh
   ollama pull qwen2.5:7b
   ```

   Model weights are not included in PFOS or its DMG. Larger models generally
   require more disk space and memory, and can respond more slowly. Intel Macs
   use CPU inference with Ollama; Apple Silicon can use CPU and GPU. A model
   can be installed successfully but still be too slow or memory-intensive for
   a particular computer. Choose based on the computer's available memory and
   Ollama's model and GPU guidance.

## Disable Ollama cloud features

The Ollama documentation supports either a server configuration file or an
environment variable. The file is convenient for the Ollama macOS app:

1. Create or edit `~/.ollama/server.json`.
2. Set this JSON value (preserve any other existing settings):

   ```json
   {
     "disable_ollama_cloud": true
   }
   ```

3. Restart Ollama. Its logs should indicate cloud is disabled.

Alternatively, set `OLLAMA_NO_CLOUD=1` in the environment used to start Ollama,
then restart it. See Ollama's current
[cloud privacy configuration](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features)
for the latest instructions. PFOS cannot inspect or enforce this setting.

## Enable Ollama in the macOS desktop app

The current DMG is an Intel x64 build. Its app supports macOS 13 and newer, but
the current Ollama macOS app requires macOS 14 or newer. The versions that can
run both applications are therefore Intel Macs on macOS 14 or newer. Ollama
lists Intel Macs as CPU-only; local inference may be slow, especially with
larger models. Apple Silicon and Windows installers are not part of the current
DMG build.

The desktop launcher passes only these two optional, non-secret variables to
its isolated backend. It continues to discard server database URLs, provider
credentials, and other inherited environment settings.

After Ollama is installed, its cloud features are disabled, and a local model
is downloaded, run these commands in Terminal:

```sh
launchctl setenv PFOS_OLLAMA_ENABLED true
launchctl setenv PFOS_OLLAMA_MODEL qwen2.5:7b
```

Then fully quit and reopen PFOS. These launch-agent settings apply to apps
started from your macOS user session. They configure PFOS to use the named
model; they do not download the model or configure Ollama cloud behavior.

To disable the PFOS integration, run:

```sh
launchctl unsetenv PFOS_OLLAMA_ENABLED
launchctl unsetenv PFOS_OLLAMA_MODEL
```

Then quit and reopen PFOS. If Ollama or the configured model is unavailable,
the app-help guide and deterministic PFOS financial workflows remain available.

## Enable Ollama in local development

Set these values in the local backend environment (for example, the untracked
`.env` file used by the API), then restart the API:

```dotenv
PFOS_OLLAMA_ENABLED=true
PFOS_OLLAMA_MODEL=qwen2.5:7b
```

Do not commit `.env`. Keep Ollama bound to loopback; PFOS's provider is fixed to
`127.0.0.1:11434` and does not accept a remote URL.

## What PFOS sends to Ollama

- Bounded, in-memory conversation history for the current chat session.
- Relevant PFOS help excerpts for app-help questions.
- For a requested calculation, the minimum summary or scenario output needed
  for the model to explain the PFOS result. Category and goal labels may also be
  included. Full transaction histories are not sent.

The backend authenticates the request and enforces household and selected-view
scope before it runs a tool. The model has no direct database, SQL, shell, or
arbitrary API access. Conversation history is held in the app's memory and is
cleared when the chat is cleared or the user signs out; it is not written to
browser storage or the PFOS database.

PFOS can avoid sending prompts to a cloud model, but the computer, operating
system, and Ollama installation remain part of the privacy boundary. Keep
Ollama cloud features disabled if you require local-only inference, and review
Ollama's current [privacy documentation](https://docs.ollama.com/faq#does-ollama-send-my-prompts-and-answers-back-to-ollama.com).
