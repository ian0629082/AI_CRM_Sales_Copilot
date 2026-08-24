import { apiRequest } from "@/lib/api/client";
import type { Interaction, InteractionCreate } from "@/lib/api/types";

export function listInteractions(leadId: number): Promise<Interaction[]> {
  return apiRequest<Interaction[]>(`/leads/${leadId}/interactions`);
}

export function createInteraction(
  leadId: number,
  payload: InteractionCreate,
): Promise<Interaction> {
  return apiRequest<Interaction>(`/leads/${leadId}/interactions`, {
    method: "POST",
    body: payload,
  });
}

export function deleteInteraction(
  leadId: number,
  interactionId: number,
): Promise<void> {
  return apiRequest<void>(`/leads/${leadId}/interactions/${interactionId}`, {
    method: "DELETE",
  });
}
