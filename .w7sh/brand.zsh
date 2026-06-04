# W7SH terminal identity
# Brand source of truth: https://github.com/xXw7shXx/w7sh-brand
# Rules/memory source of truth: https://github.com/xXw7shXx/w7sh-rules-memory

export W7SH_BLACK="0"
export W7SH_GREEN="46"
export W7SH_BLUE="51"
export W7SH_AMBER="214"
export W7SH_RED="196"
export W7SH_SMOKE="245"

autoload -Uz colors && colors

w7sh_status_segment() {
  local code="$?"
  if [ "$code" -eq 0 ]; then
    print -n "%F{$W7SH_GREEN}[OK]%f"
  else
    print -n "%F{$W7SH_RED}[FAIL:$code]%f"
  fi
}

setopt PROMPT_SUBST
PROMPT='$(w7sh_status_segment) %F{$W7SH_GREEN}W7SH%f %F{$W7SH_SMOKE}%1~%f %# '
RPROMPT='%F{$W7SH_BLUE}%D{%H:%M:%S}%f'

alias w7sh-ok='printf "\033[38;5;46m[W7SH] [OK]\033[0m %s\n"'
alias w7sh-info='printf "\033[38;5;51m[W7SH] [INFO]\033[0m %s\n"'
alias w7sh-warn='printf "\033[38;5;214m[W7SH] [WARN]\033[0m %s\n"'
alias w7sh-fail='printf "\033[38;5;196m[W7SH] [FAIL]\033[0m %s\n"'
