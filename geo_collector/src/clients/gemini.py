"""
Gemini Client (google-genai SDK)

Uses the unified google-genai SDK with Vertex AI backend.
"""
import json
import logging
from typing import Optional
from google import genai
from google.genai import types
from geo_common.llm import resolve_model_region
from src.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class GeminiClient:
    """Google GenAI Gemini Client (Vertex AI backend)"""

    def __init__(self):
        self.project_id = settings.GCP_PROJECT_ID
        self.model_id = settings.GEMINI_MODEL_ID
        self._current_region: Optional[str] = None
        self._client: Optional[genai.Client] = None
        self._model_region_overrides: Optional[str] = None

    def set_model_region_overrides(self, overrides_value: Optional[str]) -> None:
        """Set DB-loaded model region overrides for subsequent calls."""
        self._model_region_overrides = overrides_value

    def _resolve_region(self, model_id: str) -> str:
        """Determine the correct region for a given model ID.

        ``model_region_overrides`` can route GA models such as
        ``gemini-3.5-flash`` to the global endpoint without changing the
        existing string-valued model-id settings.
        """
        return resolve_model_region(
            model_id,
            overrides_value=self._model_region_overrides,
            default_region=settings.GCP_REGION,
            global_region=settings.GCP_REGION_GLOBAL,
        )

    def _ensure_client(self, model_id: Optional[str] = None):
        """Lazy initialization of genai Client.

        Dynamically switches region when the target model requires a different
        region than the currently initialized one (e.g., preview vs stable).
        """
        effective_model = model_id or self.model_id
        target_region = self._resolve_region(effective_model)

        if self._client is None or target_region != self._current_region:
            if not self.project_id:
                raise ValueError("GCP_PROJECT_ID is not set")
            logger.info(
                f"[GEMINI-S0] 初始化 GenAI Client | project={self.project_id} "
                f"| region={target_region} | model={effective_model}"
            )
            self._client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=target_region,
            )
            self._current_region = target_region
            logger.info(f"[GEMINI-S0] GenAI Client 初始化完成 | region={target_region}")
    
    async def generate_prompts(
        self,
        client_name: str,
        peers: Optional[str],
        topic: Optional[str],
        product: Optional[str],
        target_user: Optional[dict],
        intent: str,
        n: int = 20
    ) -> list[str]:
        """
        Generate N search prompts based on business information.
        
        Args:
            client_name: Focus client/brand name
            peers: Competitor names (comma separated) - ONLY used when intent is "Competitive Evaluation"
            topic: Product category
            product: Product name
            target_user: Target user profile (JSONB)
            intent: Intent type (Solution Discovery, Competitive Evaluation, Specifics Inquiry)
            n: Number of prompts to generate
            
        Returns:
            list[str]: N prompt strings
        """
        self._ensure_client()

        if isinstance(peers, list):
            peers = ", ".join(peers)

        # Only pass peers when intent is Competitive Evaluation
        effective_peers = peers if intent == "Competitive Evaluation" else None

        # Build user prompt with intent-specific guidance
        user_prompt = self._build_user_prompt(
            client_name=client_name,
            peers=effective_peers,
            topic=topic,
            product=product,
            target_user=target_user,
            intent=intent,
            n=n
        )

        logger.info(f"[GEMINI-S1] 开始生成 prompts | client={client_name} | intent={intent} | n={n} | include_peers={effective_peers is not None}")
        logger.debug(f"[GEMINI-S1] User prompt: {user_prompt[:200]}...")

        try:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.8,
                max_output_tokens=4096,
            )

            logger.info(f"[GEMINI-S2] 调用 Gemini API (async)...")
            response = await self._client.aio.models.generate_content(
                model=self.model_id,
                contents=user_prompt,
                config=config,
            )
            
            logger.info(f"[GEMINI-S2] Gemini API 调用成功 | resp_len={len(response.text)}")
            
            # Parse JSON response
            result = json.loads(response.text)
            
            # Handle different response formats
            if isinstance(result, list):
                prompts = result
            elif isinstance(result, dict) and "prompts" in result:
                prompts = result["prompts"]
            else:
                logger.error(f"[GEMINI-S3] 响应格式异常 | result_type={type(result)}")
                raise ValueError("Invalid response format from Gemini")
            
            logger.info(f"[GEMINI-S3] 解析完成 | generated={len(prompts)} prompts | requested={n}")
            return prompts[:n]
            
        except json.JSONDecodeError as e:
            logger.error(f"[GEMINI-ERR] JSON 解析失败 | error={e}")
            logger.error(f"[GEMINI-ERR] Raw response: {response.text[:500]}")
            raise
        except Exception as e:
            logger.error(f"[GEMINI-ERR] 生成失败 | error={e}")
            raise

    async def generate_content_async(
        self,
        contents: str,
        model: Optional[str] = None,
        config: Optional[types.GenerateContentConfig] = None,
        # Legacy kwarg support for callers still passing generation_config
        generation_config: Optional[types.GenerateContentConfig] = None,
    ):
        """
        Generic async content generation, used by FinalPromptBuilder for prompt fusion.

        Dynamically resolves the correct region based on the model being used.
        Model-specific overrides route GA/global-only models without changing
        existing model-id settings.

        Args:
            contents: The prompt text to send to Gemini.
            model: Optional model ID override.
            config: Optional GenerateContentConfig override.
            generation_config: Legacy alias for config (backwards compat).

        Returns:
            GenerateContentResponse from google-genai.
        """
        effective_model_id = model or self.model_id
        effective_config = config or generation_config
        # Re-initialize client with correct region if the target model requires it
        self._ensure_client(model_id=effective_model_id)

        return await self._client.aio.models.generate_content(
            model=effective_model_id,
            contents=contents,
            config=effective_config,
        )

    def _build_user_prompt(
        self,
        client_name: str,
        peers: Optional[str],
        topic: Optional[str],
        product: Optional[str],
        target_user: Optional[dict],
        intent: str,
        n: int
    ) -> str:
        """Build user prompt with intent-specific examples and guidance
        
        Field usage per intent:
        - Solution Discovery: product, topic (NO client_name)
        - Competitive Evaluation: client_name, peers, product
        - Specifics Inquiry: client_name, product, topic
        """
        
        # Use product or topic for category-level prompts
        product_category = product or topic or "product"
        # Use client_name + product for specific product references
        specific_product = f"{client_name} {product}" if client_name and product else (product or client_name or "product")
        
        # Intent-specific prompt patterns and examples
        intent_guidance = {
            "Solution Discovery": f"""
Intent Type: Solution Discovery (垂类最佳 & 咨询权威)
Users are looking for solutions and recommendations in a product category.

Generate prompts that:
- Use patterns like "Best X for Y", "What is X", "How to X", "Which X"
- Focus on product category, features, and decision-making criteria
- Include authoritative inquiry and category-level questions
- DO NOT mention any specific brand names (neither client nor competitors)
- Focus on the product category: {product_category}
{f'- May reference the topic: {topic}' if topic else ''}

Example Prompt Patterns (Best X for Y):
- "Best {product_category} for complex home environments"
- "Best {product_category} for 2,000 sq. ft. home with mostly carpet?"
- "Which {product_category} brand has the best object avoidance?"
- "What are the top 3 most reliable {product_category} brands in 2025?"
- "Best {product_category} under $1,000"

Example Prompt Patterns (What is X, How to X, Does X):
- "How to select a {product_category} for home?"
- "What are the most important features for today's best {product_category}"
- "Is the auto emptying feature worth the extra money?"
- "What makes one {product_category} 'smart'?"
- "How much suction for a {product_category} is enough?"
- "Is LiDAR better than camera-based navigation?"
- "Explain the difference between 'suction power' (Pa) and actual cleaning performance."
""",
            "Competitive Evaluation": f"""
Intent Type: Competitive Evaluation (优劣对比 & 替代方案)
Users are comparing different products/brands.

Generate prompts that:
- Use patterns like "X vs Y", "Alternatives to X", comparison queries
- Focus on competitive advantages and differentiation
- Include price-tier comparisons and market leadership questions
- MUST mention both the focus brand ({client_name}) and competitors ({peers or 'competitors'})
- May reference product type: {product_category}

Example Prompt Patterns (X vs Y):
- "{product_category} comparison of {client_name} vs {peers or 'competitor'}"
- "Should I get a {client_name}, a {peers or 'competitor'}, or stick with a {peers.split(',')[0].strip() if peers and ',' in peers else 'other brand'}?"
- "Are the $1,500 flagship models really that much better than the $500 ones?"
- "Best mid-range {product_category} under $600: {client_name} or {peers or 'competitor'}?"
- "Is {peers.split(',')[0].strip() if peers else 'competitor'} still the market leader, or has {client_name} overtaken them?"

Example Prompt Patterns (Alternatives to X):
- "{product_category} alternatives to {peers.split(',')[0].strip() if peers else 'competitor'}"
- "What are good alternatives to {peers or 'competitor'}?"
""",
            "Specifics Inquiry": f"""
Intent Type: Specifics Inquiry (临近购买)
Users are asking about specific product details, often near purchase decision.

Generate prompts that:
- Use patterns like "Does X", "What is the price for X", specific feature queries
- Focus on product specifications, compatibility, pricing, availability
- Include model-specific questions and technical details
- MUST mention the specific product: {specific_product}
- DO NOT mention any competitor brands
{f'- May reference the topic: {topic}' if topic else ''}

Example Prompt Patterns:
- "Does {specific_product} work in the dark?"
- "Does {specific_product} support Apple HomeKit?"
- "What is the price for {specific_product}?"
- "How long does {specific_product} battery last?"
- "{specific_product} specifications and features"
- "Is {specific_product} worth buying in 2025?"
- "What colors are available for {specific_product}?"
- "Does {specific_product} have self-emptying feature?"
- "Where to buy {specific_product}?"
- "{specific_product} official price"
"""
        }
        
        guidance = intent_guidance.get(intent, intent_guidance["Solution Discovery"])
        
        # Build the complete prompt with context-aware field usage
        parts = [
            f"You are a GEO (Generative Engine Optimization) expert.",
            f"Generate {n} unique, natural search queries that real users would type into AI search engines.",
            "",
            guidance,
            "",
            "Business Context:",
        ]
        
        # Add fields based on intent type
        if intent == "Solution Discovery":
            # Solution Discovery: product/topic only, NO client_name
            if topic:
                parts.append(f"- Product Category/Topic: {topic}")
            if product:
                parts.append(f"- Product Type: {product}")
            parts.append("- Note: DO NOT mention any brand names, focus on the product category only")
            
        elif intent == "Competitive Evaluation":
            # Competitive Evaluation: client_name + peers + product
            parts.append(f"- Focus Client/Brand: {client_name}")
            if peers:
                parts.append(f"- Competitor Brands: {peers}")
                parts.append("  (You MUST include these competitors in your comparison prompts)")
            if product:
                parts.append(f"- Product Type: {product}")
                
        else:  # Specifics Inquiry
            # Specifics Inquiry: client_name + product + topic
            parts.append(f"- Focus Client/Brand: {client_name}")
            if product:
                parts.append(f"- Specific Product: {product}")
            if topic:
                parts.append(f"- Topic/Category: {topic}")
            parts.append("- Note: DO NOT mention any competitor brands")
        
        if target_user:
            user_desc = json.dumps(target_user, ensure_ascii=False) if isinstance(target_user, dict) else str(target_user)
            parts.append(f"- Target User Profile: {user_desc}")
        
        parts.extend([
            "",
            "Requirements:",
            "1. Each prompt must be unique and diverse",
            "2. Prompts should sound like real user queries, not marketing copy",
            "3. Cover different user scenarios and question angles",
        ])
        
        # Add intent-specific requirements
        if intent == "Solution Discovery":
            parts.append("4. Focus on product category - NO brand names allowed")
        elif intent == "Competitive Evaluation":
            parts.append("4. Include competitor brand names in comparison prompts")
        else:  # Specifics Inquiry
            parts.append("4. Focus on the specific product - NO competitor brands")
        
        parts.extend([
            f"5. Generate exactly {n} prompts",
            "",
            f"Output: Return a JSON array containing exactly {n} prompt strings.",
            "Example output format: [\"prompt 1\", \"prompt 2\", ...]"
        ])
        
        return "\n".join(parts)


# Global singleton
_gemini_client: Optional[GeminiClient] = None

def get_gemini_client() -> GeminiClient:
    """Get Gemini client singleton"""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = GeminiClient()
    return _gemini_client
