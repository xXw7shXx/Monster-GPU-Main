# W7SH OpenCode Integration
# Global aliases for the AI engineering environment

alias oc='opencode'
alias w7sh='cd ~/GitHub/w7sh-rules-memory'
alias w7sh-memory='cd /Users/john/w7sh-agent/ai-agent-memory'

# Launch OpenCode with specific W7SH skills
alias oc-plan='opencode --skill planning'
alias oc-code='opencode --skill coding'
alias oc-review='opencode --skill review'
alias oc-loc='opencode --skill localization'
alias oc-deploy='opencode --skill deployment'

# Environment variables for model routing hints (if supported by custom plugins)
export OPENCODE_DEFAULT_PLANNER="deepseek/deepseek-v4-pro"
export OPENCODE_DEFAULT_CODER="zai-coding-plan/glm-5.1"
