# W7SH OpenCode Integration
# Global aliases for the AI engineering environment

# Ensure opencode is in PATH
export PATH="\$HOME/.local/bin:\$HOME/.opencode/bin:\$PATH"

alias oc="opencode"
alias w7sh="cd ~/GitHub/w7sh-rules-memory"
alias w7sh-memory="cd ~/w7sh-agent/ai-agent-memory"

# Launch OpenCode with specific W7SH skills
alias oc-plan="opencode --skill planning"
alias oc-code="opencode --skill coding"
alias oc-review="opencode --skill review"
alias oc-loc="opencode --skill localization"
alias oc-deploy="opencode --skill deployment"

# Environment variables for model routing hints
export OPENCODE_DEFAULT_PLANNER="deepseek/deepseek-v4-pro"
export OPENCODE_DEFAULT_CODER="zai-coding-plan/glm-5.1"
