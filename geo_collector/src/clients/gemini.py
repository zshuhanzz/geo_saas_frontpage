"""
Gemini Client for Vertex AI

Uses Google Cloud Vertex AI to call Gemini model for prompt expansion.
"""
import json
import logging
from typing import Optional
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
from src.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class GeminiClient:
    """Vertex AI Gemini Client"""
    
    def __init__(self):
        self.project_id = settings.GCP_PROJECT_ID
        self.region = settings.GCP_REGION
        self.model_id = settings.GEMINI_MODEL_ID
        self._initialized = False
        self._model: Optional[GenerativeModel] = None
    
    def _ensure_initialized(self):
        """Lazy initialization of Vertex AI SDK"""
        if not self._initialized:
            if not self.project_id:
                raise ValueError("GCP_PROJECT_ID is not set")
            logger.info(f"[GEMINI-S0] 初始化 Vertex AI | project={self.project_id} | region={self.region} | model={self.model_id}")
            vertexai.init(project=self.project_id, location=self.region)
            self._model = GenerativeModel(self.model_id)
            self._initialized = True
            logger.info(f"[GEMINI-S0] Vertex AI 初始化完成")
    
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
        self._ensure_initialized()
        
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
            # Use JSON mode for structured output
            generation_config = GenerationConfig(
                response_mime_type="application/json",
                temperature=0.8,
                max_output_tokens=4096
            )
            
            logger.info(f"[GEMINI-S2] 调用 Gemini API...")
            response = self._model.generate_content(
                contents=user_prompt,
                generation_config=generation_config,
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
        """Build user prompt with intent-specific examples and guidance"""
        
        product_name = product or topic or "product"
        
        # Intent-specific prompt patterns and examples
        intent_guidance = {
            "Solution Discovery": f"""
Intent Type: Solution Discovery
Users are looking for solutions and recommendations. Generate prompts that:
- Use patterns like "Best X for Y", "What is X", "How to X", "Does X"
- Focus on user needs, features, and decision-making
- Include authoritative inquiry and category-level questions
- DO NOT mention any competitor brands, focus only on the product category and the focus brand

Example Prompt Patterns:
- "Best {product_name} for complex home environments"
- "Best {product_name} for 2,000 sq. ft. home with mostly carpet?"
- "Which {product_name} brand has the best object avoidance?"
- "What are the top 3 most reliable {product_name} brands in 2025?"
- "Best {product_name} under $1,000"
- "How to select a {product_name} for home?"
- "What are the most important features for today's best {product_name}"
- "Is the auto emptying feature worth the extra money for {product_name}?"
- "How much suction for a {product_name} is enough?"
- "Is LiDAR better than camera-based navigation for {product_name}?"
""",
            "Competitive Evaluation": f"""
Intent Type: Competitive Evaluation
Users are comparing different products/brands. Generate prompts that:
- Use patterns like "X vs Y", "Alternatives to X", comparison queries
- Focus on competitive advantages and differentiation
- Include price-tier comparisons and market leadership questions
- MUST include competitor brand comparisons

Example Prompt Patterns:
- "{product_name} comparison of {client_name} vs {peers or 'competitor'}"
- "Should I get a {client_name}, a {peers or 'competitor'}, or stick with another brand?"
- "Are the $1,500 flagship models really that much better than the $500 ones?"
- "Best mid-range {product_name} under $600: {client_name} or {peers or 'competitor'}?"
- "Is {peers or 'competitor'} still the market leader, or has {client_name} overtaken them?"
- "{product_name} alternatives to {peers or 'competitor'}"
- "{client_name} vs {peers or 'competitor'}: which is better for pet hair?"
""",
            "Specifics Inquiry": f"""
Intent Type: Specifics Inquiry  
Users are asking about specific product details, often near purchase. Generate prompts that:
- Use patterns like "Does X", "What is the price for X", specific feature queries
- Focus on product specifications, compatibility, pricing
- Include model-specific questions and technical details
- DO NOT mention any competitor brands

Example Prompt Patterns (mix of brand-specific and product-category questions):
- "Does {product_name} work in the dark?"
- "Does {product_name} support Apple HomeKit?"
- "What is the price for {product_name}?"
- "How long does {product_name} battery last?"
- "{product_name} specifications and features"
- "Is {product_name} worth buying in 2025?"
- "What colors are available for {product_name}?"
- "Does {product_name} have self-emptying feature?"
- "{client_name} official price"
- "Where to buy {client_name} {product_name}?"
"""
        }
        
        guidance = intent_guidance.get(intent, intent_guidance["Solution Discovery"])
        
        # Build the complete prompt
        parts = [
            f"You are a GEO (Generative Engine Optimization) expert.",
            f"Generate {n} unique, natural search queries that real users would type into AI search engines.",
            "",
            guidance,
            "",
            "Business Context:",
            f"- Focus Client/Brand: {client_name}",
        ]
        
        # Only include peers for Competitive Evaluation intent
        if peers and intent == "Competitive Evaluation":
            parts.append(f"- Competitor Brands: {peers}")
            parts.append("  (You MUST include these competitors in your comparison prompts)")
        elif intent != "Competitive Evaluation":
            parts.append("- Competitor Brands: (DO NOT mention any competitors, focus on the product category only)")
        
        if topic:
            parts.append(f"- Product Category: {topic}")
        
        if product:
            parts.append(f"- Product Type: {product}")
        
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
        if intent == "Competitive Evaluation":
            parts.append("4. Include competitor brand names in comparison prompts")
        else:
            parts.append("4. DO NOT mention any competitor brands - focus on product category and focus brand ONLY")
        
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
