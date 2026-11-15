import './office-workspace-chrome.css'
import './office-ui-theme.css'
import type {EditorShell} from './shell'

/** Hide the retired report toolbar; Office owns its ribbon and commands. */
export function configureOfficeWorkspaceChrome(root:HTMLElement,_shell:EditorShell) {
  root.classList.add('office-ui-theme','office-workspace-native')
  return {dispose(){root.classList.remove('office-workspace-native')}}
}
