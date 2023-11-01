"""
This file contains examples of request and respons from Etrade JSON API
"""

success_place_trade = {
    "PlaceOrderResponse": {
        "MessageList": {},
        "Order": [
            {
                "Instrument": [
                    {
                        "Product": {"securityType": "EQ", "symbol": "IBM"},
                        "cancelQuantity": 0,
                        "orderAction": "BUY",
                        "quantity": 100,
                        "quantityType": "QUANTITY",
                        "reserveOrder": False,
                        "reserveQuantity": 0,
                        "symbolDescription": "",
                    }
                ],
                "allOrNone": False,
                "egQual": "EG_QUAL_QUALIFIED",
                "estimatedCommission": 7.99,
                "estimatedFees": 0.0,
                "gcd": 0,
                "limitPrice": 120,
                "marketSession": "REGULAR",
                "messages": {
                    "Message": [
                        {
                            "code": 1026,
                            "description": "Normal: " "order " "created",
                            "type": "WARNING",
                        }
                    ]
                },
                "netAsk": 0,
                "netBid": 0,
                "netPrice": 0,
                "orderTerm": "GOOD_UNTIL_CANCEL",
                "priceType": "LIMIT",
                "ratio": "",
                "stopPrice": 0,
            }
        ],
        "OrderIds": [{"orderId": 529}],
        "PortfolioMargin": {
            "houseExcessEquityChange": 0.0,
            "houseExcessEquityCurr": 0.0,
            "houseExcessEquityNew": 0.0,
            "pmEligible": False,
        },
        "accountId": "837108000",
        "dstFlag": False,
        "marginLevelCd": "MARGIN_TRADING_ALLOWED",
        "optionLevelCd": 4,
        "orderType": "EQ",
        "placedTime": 1354532494528,
    }
}


success_preview_order = {
    "PreviewOrderResponse": {
        "Disclosure": {
            "aoDisclosureFlag": False,
            "conditionalDisclosureFlag": True,
            "ehDisclosureFlag": False,
        },
        "MessageList": {},
        "Order": [
            {
                "Instrument": [
                    {
                        "Product": {"securityType": "EQ", "symbol": "IBM"},
                        "cancelQuantity": 0,
                        "orderAction": "BUY",
                        "quantity": 100,
                        "quantityType": "QUANTITY",
                        "reserveOrder": False,
                        "reserveQuantity": 0,
                        "symbolDescription": "",
                    }
                ],
                "allOrNone": False,
                "egQual": "EG_QUAL_OUTSIDE_GUARANTEED_PERIOD",
                "estimatedCommission": 6.99,
                "estimatedFees": 0.0,
                "gcd": 0,
                "limitPrice": 120,
                "marketSession": "EXTENDED",
                "messages": {},
                "netAsk": 0,
                "netBid": 0,
                "netPrice": 0,
                "orderTerm": "GOOD_FOR_DAY",
                "priceType": "LIMIT",
                "ratio": "",
                "stopPrice": 0,
            }
        ],
        "PortfolioMargin": {
            "houseExcessEquityChange": 0.0,
            "houseExcessEquityCurr": 0.0,
            "houseExcessEquityNew": 0.0,
            "pmEligible": False,
        },
        "PreviewIds": [{"previewId": 1627181131}],
        "accountId": "835376230",
        "dstFlag": False,
        "marginLevelCd": "MARGIN_TRADING_ALLOWED",
        "optionLevelCd": 4,
        "orderType": "EQ",
        "previewTime": 1354512315217,
    }
}


success_place_trade_response = {
    "PlaceOrderResponse": {
        "Order": [
            {
                "Instrument": [
                    {
                        "Product": {"securityType": "EQ", "symbol": "TSLA"},
                        "cancelQuantity": 0.0,
                        "orderAction": "BUY",
                        "quantity": 10,
                        "quantityType": "QUANTITY",
                        "reserveOrder": True,
                        "reserveQuantity": 0.0,
                        "symbolDescription": "TESLA " "INC " "COM",
                    }
                ],
                "allOrNone": False,
                "egQual": "EG_QUAL_UNSPECIFIED",
                "estimatedCommission": 0,
                "estimatedTotalAmount": 1690,
                "gcd": 0,
                "limitPrice": 169,
                "marketSession": "REGULAR",
                "messages": {
                    "Message": [
                        {
                            "code": 1027,
                            "description": "200|The "
                            "market "
                            "was "
                            "closed "
                            "when "
                            "we "
                            "received "
                            "your "
                            "order. "
                            "It "
                            "has "
                            "been "
                            "entered "
                            "into "
                            "our "
                            "system "
                            "and "
                            "will "
                            "be "
                            "reviewed "
                            "prior "
                            "to "
                            "market "
                            "open "
                            "on "
                            "the "
                            "next "
                            "regular "
                            "trading "
                            "day. "
                            "After "
                            "market "
                            "open, "
                            "please "
                            "check "
                            "to "
                            "make "
                            "sure "
                            "your "
                            "order "
                            "was "
                            "accepted.",
                            "type": "WARNING",
                        }
                    ]
                },
                "netAsk": 0,
                "netBid": 0,
                "netPrice": 0,
                "orderTerm": "GOOD_FOR_DAY",
                "priceType": "LIMIT",
                "ratio": "",
                "stopPrice": 0,
            }
        ],
        "OrderIds": [{"orderId": 12856}],
        "accountId": "712793764",
        "dstFlag": True,
        "marginLevelCd": "MARGIN_TRADING_ALLOWED",
        "optionLevelCd": 4,
        "orderType": "EQ",
        "placedTime": 1697015600000,
    }
}


option_preview_response = {
    "PreviewOrderResponse": {
        "Disclosure": {"aoDisclosureFlag": False, "conditionalDisclosureFlag": True},
        "Order": [
            {
                "Instrument": [
                    {
                        "Product": {
                            "callPut": "CALL",
                            "expiryDay": 13,
                            "expiryMonth": 10,
                            "expiryYear": 2023,
                            "productId": {
                                "symbol": "TSLA--231013C00240000",
                                "typeCode": "OPTION",
                            },
                            "securityType": "OPTN",
                            "strikePrice": 240.0,
                            "symbol": "TSLA",
                        },
                        "cancelQuantity": 0.0,
                        "orderAction": "BUY_OPEN",
                        "osiKey": "TSLA--231013C00240000",
                        "quantity": 1,
                        "quantityType": "QUANTITY",
                        "reserveOrder": True,
                        "reserveQuantity": 0.0,
                        "symbolDescription": "TSLA " "Oct " "13 " "'23 " "$240 " "Call",
                    }
                ],
                "allOrNone": False,
                "egQual": "EG_QUAL_NOT_IN_FORCE",
                "estimatedCommission": 0.5,
                "estimatedTotalAmount": 1000.5113,
                "gcd": 0,
                "limitPrice": 10,
                "marketSession": "REGULAR",
                "messages": {
                    "Message": [
                        {
                            "code": 7084,
                            "description": "200|This "
                            "trade "
                            "may "
                            "trigger "
                            "a "
                            "Wash "
                            "Sale.",
                            "type": "WARNING",
                        }
                    ]
                },
                "netAsk": 0,
                "netBid": 0,
                "netPrice": 0,
                "orderTerm": "GOOD_FOR_DAY",
                "priceType": "LIMIT",
                "ratio": "",
                "stopPrice": 0,
            }
        ],
        "PreviewIds": [{"previewId": 1669792828106}],
        "accountId": "712793764",
        "dstFlag": True,
        "dtBpDetails": {
            "marginable": {
                "currentBp": 198790.73,
                "currentNetBp": 198790.73,
                "currentOor": 0.0,
                "currentOrderImpact": 4002.05,
                "netBp": 194788.68,
            },
            "nonMarginable": {"currentBp": 49697.68},
        },
        "marginBpDetails": {
            "marginable": {
                "currentBp": 115560.66,
                "currentNetBp": 115560.66,
                "currentOor": 0.0,
                "currentOrderImpact": 2001.02,
                "netBp": 113559.64,
            },
            "nonMarginable": {"currentBp": 49697.68},
        },
        "marginLevelCd": "MARGIN_TRADING_ALLOWED",
        "optionLevelCd": 4,
        "orderType": "OPTN",
        "previewTime": 1697100036292,
        "totalOrderValue": 1000.5113,
    }
}


success_place_option_order = {
    "PlaceOrderResponse": {
        "Order": [
            {
                "Instrument": [
                    {
                        "Product": {
                            "callPut": "CALL",
                            "expiryDay": 13,
                            "expiryMonth": 10,
                            "expiryYear": 2023,
                            "productId": {
                                "symbol": "TSLA--231013C00240000",
                                "typeCode": "OPTION",
                            },
                            "securityType": "OPTN",
                            "strikePrice": 240.0,
                            "symbol": "TSLA",
                        },
                        "cancelQuantity": 0.0,
                        "orderAction": "BUY_OPEN",
                        "osiKey": "TSLA--231013C00240000",
                        "quantity": 1,
                        "quantityType": "QUANTITY",
                        "reserveOrder": True,
                        "reserveQuantity": 0.0,
                        "symbolDescription": "TSLA " "Oct " "13 " "'23 " "$240 " "Call",
                    }
                ],
                "allOrNone": False,
                "egQual": "EG_QUAL_UNSPECIFIED",
                "estimatedCommission": 0.5,
                "estimatedTotalAmount": 1000.5113,
                "gcd": 0,
                "limitPrice": 10,
                "marketSession": "REGULAR",
                "messages": {
                    "Message": [
                        {
                            "code": 1027,
                            "description": "200|The "
                            "market "
                            "was "
                            "closed "
                            "when "
                            "we "
                            "received "
                            "your "
                            "order. "
                            "It "
                            "has "
                            "been "
                            "entered "
                            "into "
                            "our "
                            "system "
                            "and "
                            "will "
                            "be "
                            "reviewed "
                            "prior "
                            "to "
                            "market "
                            "open "
                            "on "
                            "the "
                            "next "
                            "regular "
                            "trading "
                            "day. "
                            "After "
                            "market "
                            "open, "
                            "please "
                            "check "
                            "to "
                            "make "
                            "sure "
                            "your "
                            "order "
                            "was "
                            "accepted.",
                            "type": "WARNING",
                        }
                    ]
                },
                "netAsk": 0,
                "netBid": 0,
                "netPrice": 0,
                "orderTerm": "GOOD_FOR_DAY",
                "priceType": "LIMIT",
                "ratio": "",
                "stopPrice": 0,
            }
        ],
        "OrderIds": [{"orderId": 12881}],
        "accountId": "712793764",
        "dstFlag": True,
        "marginLevelCd": "MARGIN_TRADING_ALLOWED",
        "optionLevelCd": 4,
        "orderType": "OPTN",
        "placedTime": 1697100567696,
    }
}


option_order_status = {
    "OrdersResponse": {
        "Order": [
            {
                "Events": {
                    "Event": [
                        {
                            "Instrument": [
                                {
                                    "Product": {
                                        "callPut": "CALL",
                                        "expiryDay": 13,
                                        "expiryMonth": 10,
                                        "expiryYear": 2023,
                                        "productId": {
                                            "symbol": "TSLA--231013C00240000",
                                            "typeCode": "OPTION",
                                        },
                                        "securityType": "OPTN",
                                        "strikePrice": 240,
                                        "symbol": "TSLA",
                                    },
                                    "estimatedCommission": 0.5113,
                                    "estimatedFees": 0.0,
                                    "filledQuantity": 1.0,
                                    "orderAction": "BUY_OPEN",
                                    "orderedQuantity": 1,
                                    "quantityType": "QUANTITY",
                                    "symbolDescription": "TSLA "
                                    "Oct "
                                    "13 "
                                    "'23 "
                                    "$240 "
                                    "Call",
                                }
                            ],
                            "dateTime": 1697100567696,
                            "name": "ORDER_PLACED",
                        }
                    ]
                },
                "OrderDetail": [
                    {
                        "Instrument": [
                            {
                                "Product": {
                                    "callPut": "CALL",
                                    "expiryDay": 13,
                                    "expiryMonth": 10,
                                    "expiryYear": 2023,
                                    "productId": {
                                        "symbol": "TSLA--231013C00240000",
                                        "typeCode": "OPTION",
                                    },
                                    "securityType": "OPTN",
                                    "strikePrice": 240,
                                    "symbol": "TSLA",
                                },
                                "estimatedCommission": 0.5113,
                                "estimatedFees": 0.0,
                                "filledQuantity": 0.0,
                                "orderAction": "BUY_OPEN",
                                "orderedQuantity": 1,
                                "quantityType": "QUANTITY",
                                "symbolDescription": "TSLA "
                                "Oct "
                                "13 "
                                "'23 "
                                "$240 "
                                "Call",
                            }
                        ],
                        "allOrNone": False,
                        "gcd": 0,
                        "limitPrice": 10,
                        "marketSession": "REGULAR",
                        "netAsk": 0,
                        "netBid": 0,
                        "netPrice": 0,
                        "orderTerm": "GOOD_FOR_DAY",
                        "orderValue": 1000.5113,
                        "placedTime": 1697100567696,
                        "priceType": "LIMIT",
                        "ratio": "",
                        "status": "OPEN",
                        "stopPrice": 0,
                    }
                ],
                "orderId": 12881,
                "orderType": "OPTN",
            }
        ]
    }
}


option_quote = {
    "QuoteResponse": {
        "QuoteData": [
            {
                "All": {
                    "adjustedFlag": False,
                    "ask": 23.55,
                    "askSize": 0,
                    "askTime": "00:01:00 EDT 10-11-2023",
                    "averageVolume": 2147,
                    "beta": 0.0,
                    "bid": 22.8,
                    "bidExchange": "",
                    "bidSize": 0,
                    "bidTime": "00:01:00 EDT 10-11-2023",
                    "cashDeliverable": 0,
                    "changeClose": 0.0,
                    "changeClosePercentage": 0.0,
                    "companyName": "TESLA INC COM",
                    "contractSize": 100.0,
                    "daysToExpiration": 2,
                    "declaredDividend": 0.0,
                    "dirLast": "",
                    "dividend": 0.0,
                    "dividendPayableDate": 0,
                    "eps": 0.0,
                    "estEarnings": 0.0,
                    "exDividendDate": 0,
                    "expirationDate": 1697188879,
                    "high": 23.45,
                    "high52": 41.67,
                    "intrinsicValue": 22.99,
                    "lastTrade": 23.45,
                    "low": 23.45,
                    "low52": 9.15,
                    "marketCap": 0.0,
                    "nextEarningDate": "",
                    "open": 0.0,
                    "openInterest": 3189,
                    "optionMultiplier": 100.0,
                    "optionPreviousAskPrice": 23.55,
                    "optionPreviousBidPrice": 22.8,
                    "optionStyle": "AMERICAN",
                    "optionUnderlier": "TSLA",
                    "optionUnderlierExchange": "NSDQ",
                    "osiKey": "TSLA--231013C00240000",
                    "pe": 0.0,
                    "previousClose": 23.45,
                    "previousDayVolume": 0,
                    "primaryExchange": "CINC",
                    "sharesOutstanding": 0,
                    "symbolDescription": "TSLA Oct 13 " "'23 $240 Call",
                    "timeOfLastTrade": 1696996860,
                    "timePremium": 0.185,
                    "totalVolume": 0,
                    "upc": 0,
                    "week52HiDate": 0,
                    "week52LowDate": 0,
                    "yield": 0.0,
                },
                "Product": {
                    "callPut": "CALL",
                    "expiryDay": 13,
                    "expiryMonth": 10,
                    "expiryYear": 2023,
                    "securityType": "OPTN",
                    "strikePrice": 240.0,
                    "symbol": "TSLA",
                },
                "ahFlag": "true",
                "dateTime": "00:01:00 EDT 10-11-2023",
                "dateTimeUTC": 1696996860,
                "quoteStatus": "CLOSING",
            }
        ]
    }
}


order_status_executed_order = {
    "OrdersResponse": {
        "Order": [
            {
                "orderId": 12937,
                "orderType": "OPTN",
                "OrderDetail": [
                    {
                        "placedTime": 1697641737039,
                        "executedTime": 1697641738993,
                        "orderValue": 1925.5113,
                        "status": "EXECUTED",
                        "orderTerm": "GOOD_FOR_DAY",
                        "priceType": "LIMIT",
                        "limitPrice": 19.25,
                        "stopPrice": 0,
                        "marketSession": "REGULAR",
                        "allOrNone": False,
                        "netPrice": 0,
                        "netBid": 0,
                        "netAsk": 0,
                        "gcd": 0,
                        "ratio": "",
                        "Instrument": [
                            {
                                "symbolDescription": "TSLA Oct 20 '23 $230 Call",
                                "orderAction": "BUY_OPEN",
                                "quantityType": "QUANTITY",
                                "orderedQuantity": 1,
                                "filledQuantity": 1.0,
                                "averageExecutionPrice": 19.25,
                                "estimatedCommission": 0.5113,
                                "estimatedFees": 0.0,
                                "Product": {
                                    "symbol": "TSLA",
                                    "securityType": "OPTN",
                                    "callPut": "CALL",
                                    "expiryYear": 2023,
                                    "expiryMonth": 10,
                                    "expiryDay": 20,
                                    "strikePrice": 230,
                                    "productId": {
                                        "symbol": "TSLA--231020C00230000",
                                        "typeCode": "OPTION",
                                    },
                                },
                            }
                        ],
                    }
                ],
                "Events": {
                    "Event": [
                        {
                            "name": "ORDER_PLACED",
                            "dateTime": 1697641737039,
                            "Instrument": [
                                {
                                    "symbolDescription": "TSLA Oct 20 '23 $230 Call",
                                    "orderAction": "BUY_OPEN",
                                    "quantityType": "QUANTITY",
                                    "orderedQuantity": 1,
                                    "filledQuantity": 1.0,
                                    "averageExecutionPrice": 19.25,
                                    "estimatedCommission": 0.5113,
                                    "estimatedFees": 0.0,
                                    "Product": {
                                        "symbol": "TSLA",
                                        "securityType": "OPTN",
                                        "callPut": "CALL",
                                        "expiryYear": 2023,
                                        "expiryMonth": 10,
                                        "expiryDay": 20,
                                        "strikePrice": 230,
                                        "productId": {
                                            "symbol": "TSLA--231020C00230000",
                                            "typeCode": "OPTION",
                                        },
                                    },
                                }
                            ],
                        },
                        {
                            "name": "ORDER_EXECUTED",
                            "dateTime": 1697641738993,
                            "Instrument": [
                                {
                                    "symbolDescription": "TSLA Oct 20 '23 $230 Call",
                                    "orderAction": "BUY_OPEN",
                                    "quantityType": "QUANTITY",
                                    "orderedQuantity": 1,
                                    "filledQuantity": 1.0,
                                    "averageExecutionPrice": 19.25,
                                    "estimatedCommission": 0.5113,
                                    "estimatedFees": 0.0,
                                    "Product": {
                                        "symbol": "TSLA",
                                        "securityType": "OPTN",
                                        "callPut": "CALL",
                                        "expiryYear": 2023,
                                        "expiryMonth": 10,
                                        "expiryDay": 20,
                                        "strikePrice": 230,
                                        "productId": {
                                            "symbol": "TSLA--231020C00230000",
                                            "typeCode": "OPTION",
                                        },
                                    },
                                }
                            ],
                        },
                    ]
                },
            }
        ]
    }
}
