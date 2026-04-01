import { test } from '@playwright/test';

import { registerArtifactsModule } from './full_suite/artifacts';
import { registerAuthModule } from './full_suite/auth';
import { registerChatQuickAnswerModule } from './full_suite/chatQuickAnswer';
import { registerErrorModule } from './full_suite/errors';
import { registerEvaluationModule } from './full_suite/evaluation';
import { registerEvidenceModule } from './full_suite/evidence';
import { registerProjectDetailModule } from './full_suite/projectDetail';
import { registerProjectsModule } from './full_suite/projects';
import { registerReportModule } from './full_suite/report';
import { registerResearchRunModule } from './full_suite/researchRun';

test.describe.serial('ResearchOps Studio - Full E2E Suite', () => {
  registerAuthModule();
  registerProjectsModule();
  registerProjectDetailModule();
  registerChatQuickAnswerModule();
  registerResearchRunModule();
  registerArtifactsModule();
  registerEvidenceModule();
  registerEvaluationModule();
  registerReportModule();
  registerErrorModule();
});
