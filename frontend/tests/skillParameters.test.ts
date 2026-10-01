import { describe, expect, it } from 'vitest'
import { parameterFields, parseSkillVariables } from '../src/domain/skillParameters'

describe('skill parameter editing', () => {
  it('uses scalar controls for common schema fields', () => {
    const fields = parameterFields({ type: 'object', required: ['tone'], properties: {
      tone: { type: 'string', enum: ['calm', 'concise'] },
      count: { type: 'integer', minimum: 1 },
      flag: { type: 'boolean' },
    } })!
    expect(fields.map(field => [field.name, field.type, field.required])).toEqual([
      ['tone', 'string', true], ['count', 'integer', false], ['flag', 'boolean', false],
    ])
  })
  it.each([
    undefined, { type: 'object', properties: { nested: { type: 'object' } } },
    { type: 'object', properties: { value: { $ref: '#/$defs/value' } } },
    { type: 'object', properties: {}, oneOf: [] },
    { type: 'object', properties: { value: { type: 'string', enum: [{}] } } },
  ])('preserves complex schemas through JSON editing', schema => {
    expect(parameterFields(schema)).toBeNull()
  })
  it('does not coerce variables or insert defaults', () => {
    expect(parseSkillVariables('{"count":"3","flag":false,"nested":[1]}')).toEqual({ count: '3', flag: false, nested: [1] })
  })
  it.each(['[]', 'null', '3', '"text"', '{'])('rejects invalid variable objects', value => {
    expect(() => parseSkillVariables(value)).toThrow()
  })
})
