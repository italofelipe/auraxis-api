from marshmallow import Schema, fields, validate


class AIChatRequestSchema(Schema):
    """Request body for POST /ai/chat (Ask anything)."""

    class Meta:
        name = "AIChatRequest"

    question = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=1000),
        metadata={
            "description": "Pergunta do usuário sobre as próprias finanças.",
            "example": "Quanto gastei com alimentação até agora?",
        },
    )
