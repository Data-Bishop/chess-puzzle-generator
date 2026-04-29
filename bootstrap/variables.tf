variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-north-1"
}

variable "project_name" {
  description = "Project name — used as a prefix for all resource names"
  type        = string
  default     = "chess-puzzle-generator"
}


variable "github_repo" {
  description = "GitHub repository in owner/repo format (e.g. Data-Bishop/chess-puzzle-generator)"
  type        = string
  default     = "Data-Bishop/chess-puzzle-generator"
}
