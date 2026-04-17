from mongoengine import (ComplexDateTimeField, DictField, Document, FloatField,
                         ListField, StringField)


class WedgePopAiAnalysis(Document):
    ticker = StringField(required=True)
    trade_date = ComplexDateTimeField(required=True)
    methodology = StringField(required=True, default='oliver_kell')
    score = FloatField()
    verdict = StringField()
    trend_template = StringField()
    relative_strength = StringField()
    base_pattern = StringField()
    volume_signal = StringField()
    fundamental_signal = StringField()
    entry = StringField()
    stop = StringField()
    target = StringField()
    reasoning = ListField(StringField())
    market_posture = StringField()
    top_picks = ListField(StringField())
    avoid = ListField(StringField())
    extra_fields = DictField(default=dict)

    meta = {
        'ordering': ['trade_date', 'ticker'],
        'index_background': True,
        'auto_create_index': True,
        'auto_create_index_on_save': False,
        'indexes': [
            {'fields': ['trade_date', 'ticker', 'methodology'], 'unique': True},
            {'fields': ['trade_date', 'methodology']},
            {'fields': ['ticker', 'trade_date']},
        ]
    }
