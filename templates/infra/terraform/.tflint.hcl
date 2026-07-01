# tflint config. The `terraform` ruleset is bundled with tflint (no plugin
# download needed). Add cloud plugins (aws/azurerm/google) here when relevant.
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}
