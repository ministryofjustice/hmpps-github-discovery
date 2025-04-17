# Repository model based on the one from
# https://github.com/ministryofjustice/github-community/tree/main/app/projects/repository_standards/models

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


class RepositoryInfoFactory:
  @staticmethod
  def from_github_repo(
    repo,
  ):
    basic_info = BasicRepositoryInfo(
      name=repo.name,
      visibility=repo.visibility,
      description=repo.description,
      default_branch_name=repo.default_branch,
      license=repo.license.key if repo.license else None,
      delete_branch_on_merge=repo.delete_branch_on_merge,
      has_issues=repo.has_issues,
      owner=repo.owner,
    )

    security_and_analysis = repo.security_and_analysis
    security_analysis = SecurityAndAnalysisInfo(
      secret_scanning_status=getattr(
        security_and_analysis.secret_scanning, 'status', None
      ),
      secret_scanning_validity_checks=getattr(
        security_and_analysis.secret_scanning_validity_checks, 'status', None
      ),
      push_protection_status=getattr(
        security_and_analysis.secret_scanning_push_protection, 'status', None
      ),
      advanced_security=getattr(
        security_and_analysis.advanced_security, 'status', None
      ),
      non_provider_patterns=getattr(
        security_and_analysis.secret_scanning_non_provider_patterns,
        'status',
        None,
      ),
    )

    try:
      default_branch_protection = repo.get_branch(repo.default_branch).get_protection()
      pr = (
        default_branch_protection.required_pull_request_reviews
        if default_branch_protection
        else None
      )
      default_branch_protection = BranchProtectionInfo(
        enabled=getattr(default_branch_protection, 'enabled', False),
        allow_force_pushes=getattr(
          default_branch_protection, 'allow_force_pushes', False
        ),
        enforce_admins=getattr(default_branch_protection, 'enforce_admins', False),
        required_signatures=getattr(
          default_branch_protection, 'required_signatures', False
        ),
        dismiss_stale_reviews=getattr(pr, 'dismiss_stale_reviews', False),
        require_code_owner_reviews=getattr(pr, 'require_code_owner_reviews', False),
        require_last_push_approval=getattr(pr, 'require_last_push_approval', False),
        required_approving_review_count=getattr(
          pr, 'required_approving_review_count', 0
        ),
      )
    except Exception as e:
      default_branch_protection = None
      logger.error('Error getting default branch protection: %s', e)

    return RepositoryInfo(
      basic=basic_info,
      security_and_analysis=security_analysis,
      default_branch_protection=default_branch_protection or BranchProtectionInfo(),
    )


@dataclass
class BasicRepositoryInfo:
  name: str
  visibility: str
  delete_branch_on_merge: bool
  default_branch_name: str
  description: Optional[str] = None
  license: Optional[str] = None
  has_issues: Optional[bool] = None
  owner: Optional[str] = None


@dataclass
class SecurityAndAnalysisInfo:
  secret_scanning_status: Optional[str] = None
  secret_scanning_validity_checks: Optional[str] = None
  push_protection_status: Optional[str] = None
  advanced_security: Optional[str] = None
  non_provider_patterns: Optional[str] = None


@dataclass
class BranchProtectionInfo:
  enabled: Optional[bool] = None
  allow_force_pushes: Optional[bool] = None
  enforce_admins: Optional[bool] = None
  required_signatures: Optional[bool] = None
  dismiss_stale_reviews: Optional[bool] = None
  require_code_owner_reviews: Optional[bool] = None
  require_last_push_approval: Optional[bool] = None
  required_approving_review_count: Optional[int] = None


@dataclass
class RepositoryInfo:
  basic: BasicRepositoryInfo
  security_and_analysis: SecurityAndAnalysisInfo = field(
    default_factory=SecurityAndAnalysisInfo
  )
  default_branch_protection: BranchProtectionInfo = field(
    default_factory=BranchProtectionInfo
  )

  def to_dict(self):
    return json.loads(json.dumps(self, default=lambda o: o.__dict__))

  @classmethod
  def from_dict(cls, data: dict) -> 'RepositoryInfo':
    return cls(
      basic=BasicRepositoryInfo(**data['basic']),
      security_and_analysis=SecurityAndAnalysisInfo(
        **data.get('security_and_analysis', {})
      ),
      default_branch_protection=BranchProtectionInfo(
        **data.get('default_branch_protection', {})
      ),
    )
